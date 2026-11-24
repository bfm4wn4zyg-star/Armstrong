# 三视图设计统一记录（2026-11-24）

## 最新 SaaS 规范

design-system.css 已按指定 token 更新：背景 #F8FAFC、正文 #0F172A、主色 #2563EB；12px 卡片圆角、8px 按钮/输入圆角、999px 状态标签；所有状态使用浅底深字及细描边。概览恢复五列独立指标卡，项目卡仍使用四列等宽网格、20px 间隔；小屏变为两列/一列，项目不足一行时不会横向拉伸。里程碑、报告、样品及抽屉共用表格、表单与按钮规范。未开始项目卡使用中性灰色状态。没有更改接口或业务数据。

## 样式盘点

app.html 保留6个内联 style 块（避免在本轮改变旧逻辑）：

1. 原始全局/表格/抽屉及早期主题规则。
2. Dashboard 5 布局及早期主题。
3. 系列、型号、样品模板的旧组件。
4. 浅色主题、事业部导航、健康度、响应式、历史覆盖规则，是主要的旧样式来源。
5. 提醒邮件预览样式。
6. 登录身份标签的局部样式。

外部 dashboard-polish.css 是先前的 iOS 主题；portfolio-layout.css 是已认可的总览四列网格；新增 design-system.css 最后加载，作为所有视图及抽屉共用的设计规则。后续共用组件应改这份文件，避免继续在 overview 下添加孤立规则。

## 视图与入口

| 视图 | 正式渲染入口 | 主要组件 |
| --- | --- | --- |
| overview | renderExecutiveFocus / window.overviewHtml / gateBoardHtml | portfolio-project-grid、overview-table、gate-table |
| matrix | window.matrixHtml / sampleMatrixRows | matrix、phase-row、variant-name、status |
| reports | reportsHtml / reportData / reminderPreviewHtml | report-form、report-section、report-table、reminder-message |
| 公共详情 | openProject / openVariant / openSample | variant-table、series-schedule-table、sample-table、表单及savebar |

app.html 中较早的同名 matrixHtml 是历史定义，正式版本由后面的 window.matrixHtml 覆盖；本轮按正式入口适配。

## 本轮改动

- design-system.css：颜色token、文字、按钮、胶囊筛选、状态、表格、表单、弹窗、空状态统一。
- renderSharedFilters / setSharedFilter：将原下拉选项显示为胶囊菜单，仍派发原select的change事件，保留搜索、状态、事业部、优先级、排序和重置链路。
- decorateSharedTables：读取当前语言的表头，为单元格添加data-label；手机端按字段展示，保留完整内容。
- setMatrixLayout / matrix-view-tools：矩阵增加真实记录数与网格/列表切换，保持原点击行打开型号的行为。
- drawerBody观察器：打开或刷新详情时补齐手机字段标签。
- index.html：仅更新页面资源版本。没有改接口、存储或业务字段。

## 保留功能

所有型号、里程碑、负责人、日期、确认事项、状态、进度、详情编辑保存、账号权限、双语切换、日报/周报日期选择与分组、提醒邮件本地预览保持现有逻辑。没有新增真实邮件推送、分页或取消操作；原先没有的功能不伪装成可用按钮。

## 检查与限制

内联脚本语法、共用筛选事件转发、筛选HTML、中英标签及移动字段标签采用代码级检查。1280使用紧凑表格；768和375使用无横向表格的字段卡片规则。仍需浏览器实测各尺寸及完整编辑保存回归；本轮浏览器入口返回Tab not found，不能将代码级检查称为截图验收。
