# Decisions (spec §25 — 小さな不明点はデフォルトを選び記録)

1. Meta Model API の wire 形式: 公式ドキュメント (`dev.meta.ai/docs/sam/segmenting`,
   `/docs/sam/reading-segmentation`) で確定。Base URL `https://api.meta.ai/v1`、
   Responses API、モデル名 (`muse-spark-1.3` / `sam-3.1`)。
   SAM は `stream:true`＋1メッセージ (素の noun phrase `input_text`＋`input_image`)、
   応答は special-token テキスト (`<0f>id<|box;x1;..;w;h|>...`) を蓄積して正規表現で parse。
   教訓: `Find: cup` のような接頭辞は concept 照合を壊す(空応答の原因)。素の noun phrase のみ送る。
   `metadata={"include_confidence":"true","mask_encoding":"one_bit"}` (値は文字列)。
   座標は source pixel なので token 内の `w`/`h` で正規化。空 `output_text` は正常(不在)。
   HTTP 400 は `MetaAPIPermanentError` として retry しない。公式仕様優先。
2. 距離: image-diagonal 正規化のみ。物理単位要求は `requires_metric_depth=true` で保持し UI 警告。
3. Zone 形状: 矩形を4点 polygon として統一。矩形は高速パス、任意 polygon は point-in-polygon + grid overlap。
4. Frontend に Tailwind を入れない: 依存最小化のため素の CSS。spec は「使用してもよい」なので違反なし。
5. Rule store は in-memory (spec 非ゴール: database なし)。
6. Temporal は軽量 Tracker (IoU/nearest-neighbor) を標準搭載。P0/P1 と独立した分岐のため安定性を壊さない。
7. Mock は fixture 固定レイアウト + `image_variant` (default/far/empty_zone) で移動・除去を再現。
   本番 UI では `mocked` フラグを「Mock mode」と明示。
