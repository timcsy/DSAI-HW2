import argparse

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras.models import *
from tensorflow.keras.layers import *

batch_size = 32
seq_len = 128

d_k = 256
d_v = 256
n_heads = 12
ff_dim = 256

class Time2Vector(Layer):
    def __init__(self, seq_len, **kwargs):
        super(Time2Vector, self).__init__()
        self.seq_len = seq_len

    def build(self, input_shape):
        '''Initialize weights and biases with shape (batch, seq_len)'''
        self.weights_linear = self.add_weight(
            name='weight_linear',
            shape=(int(self.seq_len),),
            initializer='uniform',
            trainable=True
        )
        
        self.bias_linear = self.add_weight(
            name='bias_linear',
            shape=(int(self.seq_len),),
            initializer='uniform',
            trainable=True
        )
        
        self.weights_periodic = self.add_weight(
            name='weight_periodic',
            shape=(int(self.seq_len),),
            initializer='uniform',
            trainable=True
        )

        self.bias_periodic = self.add_weight(
            name='bias_periodic',
            shape=(int(self.seq_len),),
            initializer='uniform',
            trainable=True
        )

    def call(self, x):
        '''Calculate linear and periodic time features'''
        x = tf.math.reduce_mean(x[:,:,:3], axis=-1) 
        time_linear = self.weights_linear * x + self.bias_linear # Linear time feature
        time_linear = tf.expand_dims(time_linear, axis=-1) # Add dimension (batch, seq_len, 1)
        
        time_periodic = tf.math.sin(tf.multiply(x, self.weights_periodic) + self.bias_periodic)
        time_periodic = tf.expand_dims(time_periodic, axis=-1) # Add dimension (batch, seq_len, 1)
        return tf.concat([time_linear, time_periodic], axis=-1) # shape = (batch, seq_len, 2)
    
    def get_config(self): # Needed for saving and loading model with custom layer
        config = super().get_config().copy()
        config.update({'seq_len': self.seq_len})
        return config

#############################################################################

class SingleAttention(Layer):
    def __init__(self, d_k, d_v):
        super(SingleAttention, self).__init__()
        self.d_k = d_k
        self.d_v = d_v

    def build(self, input_shape):
        self.query = Dense(
            self.d_k, 
            input_shape=input_shape, 
            kernel_initializer='glorot_uniform', 
            bias_initializer='glorot_uniform'
        )
        
        self.key = Dense(
            self.d_k, 
            input_shape=input_shape, 
            kernel_initializer='glorot_uniform', 
            bias_initializer='glorot_uniform'
        )
        
        self.value = Dense(
            self.d_v, 
            input_shape=input_shape, 
            kernel_initializer='glorot_uniform', 
            bias_initializer='glorot_uniform'
        )

    def call(self, inputs): # inputs = (in_seq, in_seq, in_seq)
        q = self.query(inputs[0])
        k = self.key(inputs[1])

        attn_weights = tf.matmul(q, k, transpose_b=True)
        attn_weights = tf.map_fn(lambda x: x/np.sqrt(self.d_k), attn_weights)
        attn_weights = tf.nn.softmax(attn_weights, axis=-1)
        
        v = self.value(inputs[2])
        attn_out = tf.matmul(attn_weights, v)
        return attn_out

#############################################################################

class MultiAttention(Layer):
    def __init__(self, d_k, d_v, n_heads):
        super(MultiAttention, self).__init__()
        self.d_k = d_k
        self.d_v = d_v
        self.n_heads = n_heads
        self.attn_heads = list()

    def build(self, input_shape):
        for n in range(self.n_heads):
            self.attn_heads.append(SingleAttention(self.d_k, self.d_v))  
            
            # input_shape[0]=(batch, seq_len, 6), input_shape[0][-1]=6
            self.linear = Dense(
                input_shape[0][-1], 
                input_shape=input_shape, 
                kernel_initializer='glorot_uniform', 
                bias_initializer='glorot_uniform'
            )

    def call(self, inputs):
        attn = [self.attn_heads[i](inputs) for i in range(self.n_heads)]
        concat_attn = tf.concat(attn, axis=-1)
        multi_linear = self.linear(concat_attn)
        return multi_linear

#############################################################################

class TransformerEncoder(Layer):
    def __init__(self, d_k, d_v, n_heads, ff_dim, dropout=0.1, **kwargs):
        super(TransformerEncoder, self).__init__()
        self.d_k = d_k
        self.d_v = d_v
        self.n_heads = n_heads
        self.ff_dim = ff_dim
        self.attn_heads = list()
        self.dropout_rate = dropout

    def build(self, input_shape):
        self.attn_multi = MultiAttention(self.d_k, self.d_v, self.n_heads)
        self.attn_dropout = Dropout(self.dropout_rate)
        self.attn_normalize = LayerNormalization(input_shape=input_shape, epsilon=1e-6)

        self.ff_conv1D_1 = Conv1D(filters=self.ff_dim, kernel_size=1, activation='relu')
        # input_shape[0]=(batch, seq_len, 6), input_shape[0][-1] = 6
        self.ff_conv1D_2 = Conv1D(filters=input_shape[0][-1], kernel_size=1) 
        self.ff_dropout = Dropout(self.dropout_rate)
        self.ff_normalize = LayerNormalization(input_shape=input_shape, epsilon=1e-6)    
    
    def call(self, inputs): # inputs = (in_seq, in_seq, in_seq)
        attn_layer = self.attn_multi(inputs)
        attn_layer = self.attn_dropout(attn_layer)
        attn_layer = self.attn_normalize(inputs[0] + attn_layer)

        ff_layer = self.ff_conv1D_1(attn_layer)
        ff_layer = self.ff_conv1D_2(ff_layer)
        ff_layer = self.ff_dropout(ff_layer)
        ff_layer = self.ff_normalize(inputs[0] + ff_layer)
        return ff_layer 

    def get_config(self): # Needed for saving and loading model with custom layer
        config = super().get_config().copy()
        config.update({
            'd_k': self.d_k,
            'd_v': self.d_v,
            'n_heads': self.n_heads,
            'ff_dim': self.ff_dim,
            'attn_heads': self.attn_heads,
            'dropout_rate': self.dropout_rate
        })
        return config

#############################################################################

def create_model():
    '''Initialize time and transformer layers'''
    time_embedding = Time2Vector(seq_len)
    attn_layer1 = TransformerEncoder(d_k, d_v, n_heads, ff_dim)
    attn_layer2 = TransformerEncoder(d_k, d_v, n_heads, ff_dim)
    attn_layer3 = TransformerEncoder(d_k, d_v, n_heads, ff_dim)

    '''Construct model'''
    in_seq = Input(shape=(seq_len, 4))
    x = time_embedding(in_seq)
    x = Concatenate(axis=-1)([in_seq, x])
    x = attn_layer1((x, x, x))
    x = attn_layer2((x, x, x))
    x = attn_layer3((x, x, x))
    x = GlobalAveragePooling1D(data_format='channels_first')(x)
    x = Dropout(0.1)(x)
    x = Dense(64, activation='relu')(x)
    x = Dropout(0.1)(x)
    out = Dense(1, activation='linear')(x)

    model = Model(inputs=in_seq, outputs=out)
    model.compile(loss='mse', optimizer='adam', metrics=['mae', 'mape'])
    return model

#############################################################################

def training(IBM_path: str):
    df = pd.read_csv(IBM_path, delimiter=',', header=None, names=['Open', 'High', 'Low', 'Close'])

    # Apply moving average with a window of 10 days to all columns
    df[['Open', 'High', 'Low', 'Close']] = df[['Open', 'High', 'Low', 'Close']].rolling(10).mean()

    # Drop all rows with NaN values
    df.dropna(how='any', axis=0, inplace=True)

    '''Calculate percentage change'''

    df['Open'] = df['Open'].pct_change() # Create arithmetic returns column
    df['High'] = df['High'].pct_change() # Create arithmetic returns column
    df['Low'] = df['Low'].pct_change() # Create arithmetic returns column
    df['Close'] = df['Close'].pct_change() # Create arithmetic returns column

    df.dropna(how='any', axis=0, inplace=True) # Drop all rows with NaN values

    ###############################################################################
    '''Create indexes to split dataset'''

    times = sorted(df.index.values)
    last_10pct = sorted(df.index.values)[-int(0.1*len(times))] # Last 10% of series
    last_20pct = sorted(df.index.values)[-int(0.2*len(times))] # Last 20% of series

    ###############################################################################
    '''Normalize price columns'''
    #
    min_return = min(df[(df.index < last_20pct)][['Open', 'High', 'Low', 'Close']].min(axis=0))
    max_return = max(df[(df.index < last_20pct)][['Open', 'High', 'Low', 'Close']].max(axis=0))

    # Min-max normalize price columns (0-1 range)
    df['Open'] = (df['Open'] - min_return) / (max_return - min_return)
    df['High'] = (df['High'] - min_return) / (max_return - min_return)
    df['Low'] = (df['Low'] - min_return) / (max_return - min_return)
    df['Close'] = (df['Close'] - min_return) / (max_return - min_return)

    ###############################################################################
    '''Create training, validation and test split'''

    df_train = df[(df.index < last_20pct)]  # Training data are 80% of total data
    df_val = df[(df.index >= last_20pct) & (df.index < last_10pct)]
    df_test = df[(df.index >= last_10pct)]

    # Convert pandas columns into arrays
    train_data = df_train.values
    val_data = df_val.values
    test_data = df_test.values
    print('Training data shape: {}'.format(train_data.shape))
    print('Validation data shape: {}'.format(val_data.shape))
    print('Test data shape: {}'.format(test_data.shape))

    ###############################################################################
    ###############################################################################

    # Training data
    X_train, y_train = [], []
    for i in range(seq_len, len(train_data)):
        X_train.append(train_data[i-seq_len:i]) # Chunks of training data with a length of 128 df-rows
        y_train.append(train_data[:, 3][i]) #Value of 4th column (Close Price) of df-row 128+1
    X_train, y_train = np.array(X_train), np.array(y_train)

    ###############################################################################

    # Validation data
    X_val, y_val = [], []
    for i in range(seq_len, len(val_data)):
        X_val.append(val_data[i-seq_len:i])
        y_val.append(val_data[:, 3][i])
    X_val, y_val = np.array(X_val), np.array(y_val)

    ###############################################################################

    # Test data
    X_test, y_test = [], []
    for i in range(seq_len, len(test_data)):
        X_test.append(test_data[i-seq_len:i])
        y_test.append(test_data[:, 3][i])    
    X_test, y_test = np.array(X_test), np.array(y_test)

    print('Training set shape', X_train.shape, y_train.shape)
    print('Validation set shape', X_val.shape, y_val.shape)
    print('Testing set shape' ,X_test.shape, y_test.shape)

    ###############################################################################

    model = create_model()
    model.summary()

    callback = tf.keras.callbacks.ModelCheckpoint('Transformer+TimeEmbedding.hdf5', 
                                                monitor='val_loss', 
                                                save_best_only=True, 
                                                verbose=1)

    history = model.fit(X_train, y_train, 
                        batch_size=batch_size, 
                        epochs=50,
                        callbacks=[callback],
                        validation_data=(X_val, y_val))  

    model = tf.keras.models.load_model('/content/Transformer+TimeEmbedding.hdf5',
                                    custom_objects={'Time2Vector': Time2Vector, 
                                                    'SingleAttention': SingleAttention,
                                                    'MultiAttention': MultiAttention,
                                                    'TransformerEncoder': TransformerEncoder})

    model.save('stock.h5')

    ###############################################################################

    '''Calculate predictions and metrics'''

    #Calculate predication for training, validation and test data
    train_pred = model.predict(X_train)
    val_pred = model.predict(X_val)
    test_pred = model.predict(X_test)

    #Print evaluation metrics for all datasets
    train_eval = model.evaluate(X_train, y_train, verbose=0)
    val_eval = model.evaluate(X_val, y_val, verbose=0)
    test_eval = model.evaluate(X_test, y_test, verbose=0)
    print(' ')
    print('Evaluation metrics')
    print('Training Data - Loss: {:.4f}, MAE: {:.4f}, MAPE: {:.4f}'.format(train_eval[0], train_eval[1], train_eval[2]))
    print('Validation Data - Loss: {:.4f}, MAE: {:.4f}, MAPE: {:.4f}'.format(val_eval[0], val_eval[1], val_eval[2]))
    print('Test Data - Loss: {:.4f}, MAE: {:.4f}, MAPE: {:.4f}'.format(test_eval[0], test_eval[1], test_eval[2]))

#############################################################################

def load_model():
    model = tf.keras.models.load_model(
        'stock.h5',
        custom_objects={
            'Time2Vector': Time2Vector, 
            'SingleAttention': SingleAttention,
            'MultiAttention': MultiAttention,
            'TransformerEncoder': TransformerEncoder
        }
    )
    return model

def testing(df_input):
    # Apply moving average with a window of 10 days to all columns
    df = df_input[['Open', 'High', 'Low', 'Close']].rolling(10).mean()

    # Drop all rows with NaN values
    df.dropna(how='any', axis=0, inplace=True)

    '''Calculate percentage change'''

    df['Open'] = df['Open'].pct_change() # Create arithmetic returns column
    df['High'] = df['High'].pct_change() # Create arithmetic returns column
    df['Low'] = df['Low'].pct_change() # Create arithmetic returns column
    df['Close'] = df['Close'].pct_change() # Create arithmetic returns column

    df.dropna(how='any', axis=0, inplace=True) # Drop all rows with NaN values

    ###############################################################################
    '''Normalize price columns'''
    #
    min_return = min(df[['Open', 'High', 'Low', 'Close']].min(axis=0))
    max_return = max(df[['Open', 'High', 'Low', 'Close']].max(axis=0))

    # Min-max normalize price columns (0-1 range)
    df['Open'] = (df['Open'] - min_return) / (max_return - min_return)
    df['High'] = (df['High'] - min_return) / (max_return - min_return)
    df['Low'] = (df['Low'] - min_return) / (max_return - min_return)
    df['Close'] = (df['Close'] - min_return) / (max_return - min_return)

    ###############################################################################
    '''Create training, validation and test split'''

    df_train = df  # Training data

    # Convert pandas columns into arrays
    train_data = df_train.values
    print('Training data shape: {}'.format(train_data.shape))

    ###############################################################################
    ###############################################################################

    # Training data
    X_train = []
    for i in range(seq_len, len(train_data)):
        X_train.append(train_data[i-seq_len:i]) # Chunks of training data with a length of 128 df-rows
    X_train = np.array(X_train)

    model = load_model()
    train_pred = model.predict(X_train)

    return train_pred[-1][0]

#############################################################################


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--training", default="training_data.csv", help="input training data file name")
    parser.add_argument("--testing", default="testing_data.csv", help="input testing data file name")
    parser.add_argument("--output", default="output.csv", help="output file name")
    args = parser.parse_args()

    print('Tensorflow version: {}'.format(tf.__version__))

    # You can modify it at will.
    training_path = args.training
    # training(training_path)
    df_train = pd.read_csv(training_path, delimiter=',', header=None, names=['Open', 'High', 'Low', 'Close'])
    df_train = df_train[-256:]

    testing_path = args.testing
    df_test = pd.read_csv(testing_path, delimiter=',', header=None, names=['Open', 'High', 'Low', 'Close'])

    with open(args.output, "w") as output_file:
        prev_pred = 0
        unit = 0
        for i, row in df_test.iterrows(): # read a row of testing data at one time
            if (i == len(df_test) - 1):
                break
            # We will perform your action as the open price in the next day.
            pred = testing(df_train)
            if (pred > prev_pred):
                if (unit == 0):
                    output_file.write('1\n')
                    unit += 1
                else:
                    output_file.write('0\n')
            else:
                if (unit == 1):
                    output_file.write('-1\n')
                    unit -= 1
                else:
                    output_file.write('0\n')
            
            df_train = df_train.append(row)
            prev_pred = pred
