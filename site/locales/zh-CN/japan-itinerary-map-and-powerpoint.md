# 把日本行程做成交互地图和 PowerPoint

Japan Travel Skills 可以从同一份行程生成旅行地图、适合手机查看的每日计划和同行人演示提纲。指南按日期展示对应地点和交通，可筛选酒店、景点与餐厅。没有可靠坐标的地点仍保留在清单中。生成实际 PowerPoint 文件需要宿主提供的幻灯片制作工具。

## 请智能体把旅程可视化

[安装 Japan Travel Skills（英文）](installation.md)，再给智能体一份旅行需求或现成行程。说明要继续查询并完善行程，还是只重新呈现你提供的内容。

可以单独要一种，也可以一次要几种。例如：

**旅途中用手机看**

> 把这份行程做成手机上能打开的旅行地图，按天标出景点、餐厅和酒店。再给我一份每日计划，方便按顺序看下一站去哪儿、怎么换乘。

**出发前和同伴商量**

> 把这份行程做成一份图文并茂的 PPT，给同行的朋友看。讲清楚一路怎么玩、住在哪儿、有什么好吃的，最后列出还需要大家一起决定的事。

如果草案可能有时间冲突，请先[校验行程](check-japan-itinerary.md)，再生成不同形式的交付。

## 在本地生成京都与奈良样例

在仓库根目录使用 Python 3.9 或更新版本。下面的三条命令读取同一份公开样例，生成过程可离线完成。输出目录放在仓库之外。

```bash
demo_dir="$(mktemp -d)"
python3 skills/japan-travel-planner/scripts/render_plan.py --peer daily.html \
  --input skills/japan-travel-planner/examples/kyoto-nara-demo.json \
  --output "$demo_dir/guide.html"
python3 skills/japan-travel-planner/scripts/render_plan.py --format daily --peer guide.html \
  --input skills/japan-travel-planner/examples/kyoto-nara-demo.json \
  --output "$demo_dir/daily.html"
python3 skills/japan-travel-planner/scripts/render_plan.py --format brief \
  --input skills/japan-travel-planner/examples/kyoto-nara-demo.json \
  --output "$demo_dir/presentation.md"
printf 'Example files: %s\n' "$demo_dir"
```

打开 `daily.html` 可按顺序查看当天的交通与活动，跨城日可直接跳到任一城市当天的地图。
本地打开 `guide.html`，切换京都停留和奈良一日游，也可以筛选地点或下载行程 JSON。
公开样例使用演示日期和候选安排，实际出行请另查日期条件。
Markdown 提纲提供可编辑的行程记录和页面布局建议，可交给幻灯片工具生成 PPTX。
命令使用仓库中的原始中文样例，本站的英文和日文版本由同一份记录翻译生成。

## 让地图和演示文稿保持一致

三份交付应保持日期、住宿城市、交通提示和场所条件一致。
幻灯片应使用有适当授权的图片，保留署名，并把核查范围写在对应选项旁边。
修改行程后，重新生成或更新受影响的页面。

打开指南后，会在支持的缩放范围内自动加载国土地理院底图。可以关闭底图；加载失败时仍保留地点标记和清单。地图上的点用于参考位置，步行路线和时间须另外核查。
HTML 中嵌入了完整行程，分享前请检查所有记录。详见[数据规范（英文）](../skills/japan-travel-planner/references/plan-data.md)和[交付流程（英文）](../skills/japan-travel-planner/references/deliverables.md)。
