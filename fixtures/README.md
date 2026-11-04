# Fixture frames (mock mode)

`MOCK_META_API=true` のとき `segmentation.mock_segment` が使う固定レイアウトの説明。

- `default`: laptop 左、cup 中央、bottle 右、box 中央、bag 左 → Demo 1 は violation、Demo 2 は Blocked access
- `far`: cup/bottle を右上へ移動 → Demo 1 は Resolved
- `empty_zone`: box を検出しない → Demo 2 は Resolved

## sample detection payload

```json
{
  "concept": "cup",
  "selector_id": "drink",
  "bbox": [0.55, 0.55, 0.70, 0.80],
  "confidence": 0.93
}
```

bbox は 0..1 正規化 `[x_min, y_min, x_max, y_max]`。
