# DSAI-HW2

安裝
---
```
pip install -r requirements.txt
```

執行
---
```
python trader.py --training training_data.csv --testing testing_data.csv --output output.csv
```

心得
---
- 參考：[Stock predictions with state-of-the-art Transformer and Time Embeddings](https://towardsdatascience.com/stock-predictions-with-state-of-the-art-transformer-and-time-embeddings-3a4485237de6)
- 使用 Transformer 來預測收益率曲線
- 在訓練的時候常受到初始 weight 的影響，在一些時候訓練不太起來，但是在可以訓練起來的狀況下要到大約 30 epochs 才會開始收斂