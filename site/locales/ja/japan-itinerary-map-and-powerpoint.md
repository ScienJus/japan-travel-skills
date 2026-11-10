# 日本の旅程をインタラクティブマップとPowerPointにまとめる

Japan Travel Skillsは、一つの旅程からローカルHTMLの旅行ガイドとスライド制作資料を生成できます。
日付を切り替えると立ち寄り先と交通が連動し、ホテル、観光地、飲食店で絞り込めます。
出典のある座標が得られなかった場所は一覧に残ります。PowerPointファイルの作成には、実行環境のスライド作成ツールを使います。

## エージェントに旅の可視化を頼む

[Japan Travel Skillsを導入（英語）](installation.md)し、旅行の希望や既存の旅程を渡します。
旅程の調査も依頼するか、渡した内容をそのまま別の形式にするかを伝えてください。

> この日本旅行の旅程を、japan-travel-plannerスキルでスマートフォン向けのローカルHTMLガイドにしてください。
> 地図を添え、スライド作成ツールが使える場合は写真付きのPPTXも作成してください。
> 宿泊する街、都市間の移動、観光、郷土料理と飲食店の候補を含めてください。
> 確定済みの予定、出典へのリンク、未確認事項を残し、ファイルはローカルに保存してください。

時間が合わない可能性がある下書きは、複数の形式で共有する前に[旅程を確認](check-japan-itinerary.md)しましょう。

## 京都・奈良の実例をローカルで生成する

リポジトリのルートでPython 3.9以降を使います。二つのコマンドは同じ公開サンプルを読み込み、オフラインで実行できます。出力先はリポジトリの外に指定します。

```bash
demo_dir="$(mktemp -d)"
python3 skills/japan-travel-planner/scripts/render_plan.py \
  --input skills/japan-travel-planner/examples/kyoto-nara-demo.json \
  --output "$demo_dir/guide.html"
python3 skills/japan-travel-planner/scripts/render_plan.py --format brief \
  --input skills/japan-travel-planner/examples/kyoto-nara-demo.json \
  --output "$demo_dir/presentation.md"
printf 'Example files: %s\n' "$demo_dir"
```

`guide.html`を開き、京都での滞在と奈良の日帰りを切り替えてみてください。場所の絞り込みと旅程JSONのダウンロードもできます。
日付と訪問候補はデモ用です。実際の旅行では利用日ごとの条件を確認してください。
Markdownには編集可能な旅程データとページ構成案が入り、スライド作成ツールに渡せます。
このコマンドはリポジトリ内の中国語サンプルを使用します。サイトの英語版・日本語版も同じ記録をもとにしています。

## 地図とスライドの内容をそろえる

日付、宿泊する街、交通の注意点、施設の利用条件を両方に反映します。
スライドには再利用可能な画像を使い、クレジットと確認した範囲を、関係する選択肢のそばに記載します。
旅程を変更したら、影響する地図やスライドを更新してください。

ローカルガイドは通常、外部に通信しません。利用者が地理院地図を表示した場合にのみ、背景地図の取得が行われます。
地点のマーカーは位置の目安です。実際の徒歩ルートや所要時間は別途確認してください。
HTMLには旅程全体が入るため、共有前に全記録を確認します。
詳しくは[データ仕様（英語）](../skills/japan-travel-planner/references/plan-data.md)と[制作手順（英語）](../skills/japan-travel-planner/references/deliverables.md)をご覧ください。
