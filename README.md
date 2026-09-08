# 🧩 TT_Calendar Plugins

**TT Calendar 订阅插件仓库** — 想订阅什么日历，就装什么日历。

> Community plugin repository for [TT Calendar](https://github.com/TTDiang2/TT_Calendar) (v2.3+).
> Each plugin is a single `.py` file: download → drop into `plugins/` → restart.

---

## 📦 收录插件

| 插件文件 | 数据源 | 说明 | 需要凭据 |
|---|---|---|---|
| [`investing.py`](investing.py) | 英为财情（investing.com）经济日历 | 美/中/日/欧等 16 国经济指标：时间 · 货币 · 重要性 · 今值/预测值/前值 · vs 预期；按国家分图层 | ✅ Cloudflare cookie（见下） |
| [`jisilu.py`](jisilu.py) | 集思录投资日历 | 新股 / 可转债 / 分红 / REITs / 股指期货期权等 15 类事件，按类型分图层 | ❌ 无需 |

## ⚙️ 安装

1. **下载插件文件**：点上面的文件名，再点页面右侧 **Download raw file**（或 `git clone` 本仓库后复制）
2. **放进 TT Calendar 的插件目录**：

   - **源码版**：`TT_Calendar/plugins/` 文件夹
   - **打包版（3 个 exe）**：在 exe 旁边新建 `plugins/` 文件夹

3. **重启应用** —— 完成。侧边栏会出现插件对应的图层分组，订阅面板可添加数据源。

> 装多个插件就把多个 `.py` 都放进去；卸载 = 删除文件。

## 📖 使用方法

### 添加订阅

1. 打开应用 → 侧边栏底部/顶栏打开 **订阅** 面板
2. 点 **+ 新增订阅**，选择已安装的插件源（如「英为财情-投资日历」），保存
3. 点该订阅卡片的 **「立即更新」**（或重启应用自动刷新）→ 事件写入对应图层

### 图层开关

侧边栏按分组显示各插件的图层，**勾选 = 显示并写入**，不勾选的图层不落库：

- `英为财情·美国 / 中国 / 日本 / 欧元区 …`（investing 按国家分 16 图层 + 「其他」兜底图层）
- `集思录·新股上市 / 可转债 / A股分红 …`（jisilu 按类型分 15 图层）

### 事件详情

点击日期 → 右侧详情面板：事件卡片会显示插件声明的字段
（如英为财情的 时间 · 货币 · 统计周期 · 重要性星级 + 今值/预测值/前值 + vs 预期徽标）——
字段展示由插件声明，应用自动渲染，无需装额外前端组件。

### investing 插件：CF cookie（仅此插件需要）

英为财情被 Cloudflare 保护，普通请求会被拦截。首次使用需：

1. 用 **Edge 浏览器** 打开 https://cn.investing.com/economic-calendar ，通过人机验证
2. `F12` → Application → Cookies → 选中 `cn.investing.com`，全选复制为 JSON
3. 保存到 `data/investing_cookies.json`（应用数据目录；打包版在 exe 旁 `data/` 文件夹，没有就建一个）：

   ```json
   { "cf_clearance": "…", "__cf_bm": "…" }
   ```

4. 回应用点「立即更新」—— 之后 cookie 过期（约半天~1 天）只需重新导出一次

## 🧪 测试

插件测试设计为在 **TT Calendar 源码目录**下运行（依赖 `tt_calendar` 包）：

```bash
# 在 TT_Calendar 项目根目录
python -m pytest ../TT_Calendar_Plugins/tests -q
```

- `tests/test_investing_source.py`：investing 解析器单元测试（真实抓包样本，不发真实 HTTP）

## 🤝 贡献插件

写了一个新插件？欢迎分享：

1. 在 `plugins/` 放好你的 `.py`（协议见 TT_Calendar 仓库
   [docs/SUBSCRIPTION_PLUGIN_GUIDE.md](https://github.com/TTDiang2/TT_Calendar/blob/main/docs/SUBSCRIPTION_PLUGIN_GUIDE.md)）
2. 给本仓库提 PR：插件文件放根目录，命名 `source_id.py`
3. 在下方「收录插件」表补一行，README 里说明安装与凭据要求

**协议速览**：`Source` 子类需实现 `source_id / display_name / layer_specs() / fetch(start, end)`，
可选 `field_specs()`（事件字段 UI 规格）与 `refresh_past_days / refresh_future_days`（刷新窗口）。

---

TT Calendar 主仓库：[TTDiang2/TT_Calendar](https://github.com/TTDiang2/TT_Calendar) · License: MIT
