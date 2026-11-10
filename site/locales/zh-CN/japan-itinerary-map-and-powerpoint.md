# 把日本行程做成交互地图和 PowerPoint

Japan Travel Skills 可以从同一份行程生成本地 HTML 旅行指南和演示提纲。指南按日期展示对应地点和交通，可筛选酒店、景点与餐厅。没有可靠坐标的地点仍保留在清单中。生成实际 PowerPoint 文件需要宿主提供的幻灯片制作工具。

## 请智能体把旅程可视化

[安装 Japan Travel Skills（英文）](installation.md)，再给智能体一份旅行需求或现成行程。说明要继续查询并完善行程，还是只重新呈现你提供的内容。

> 请用 japan-travel-planner 把我的日本行程做成适合手机查看的本地 HTML 地图指南。如果宿主提供幻灯片工具，也请制作图文并茂的 PPTX。
> 保留住宿城市、城际交通、景点、当地美食和餐厅候选，以及已定事项、原始链接和待确认问题。请将文件保存在本地。

如果草案可能有时间冲突，请先[校验行程](check-japan-itinerary.md)，再生成不同形式的交付。

## 在本地生成京都与奈良样例

在仓库根目录使用 Python 3.9 或更新版本。下面的两条命令读取同一份公开样例，生成过程可离线完成。输出目录放在仓库之外。

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

本地打开 `guide.html`，切换京都停留和奈良一日游，也可以筛选地点或下载行程 JSON。
公开样例使用演示日期和候选安排，实际出行请另查日期条件。
Markdown 提纲提供可编辑的行程记录和页面布局建议，可交给幻灯片工具生成 PPTX。
命令使用仓库中的原始中文样例，本站的英文和日文版本由同一份记录翻译生成。

## 让地图和演示文稿保持一致

两种交付应保持日期、住宿城市、交通提示和场所条件一致。
幻灯片应使用有适当授权的图片，保留署名，并把核查范围写在对应选项旁边。
修改行程后，重新生成或更新受影响的页面。

本地指南默认不发出外部请求。只有主动加载国土地理院底图时才会发出请求。地图上的点用于参考位置，步行路线和时间须另外核查。
HTML 中嵌入了完整行程，分享前请检查所有记录。详见[数据规范（英文）](../skills/japan-travel-planner/references/plan-data.md)和[交付流程（英文）](../skills/japan-travel-planner/references/deliverables.md)。
