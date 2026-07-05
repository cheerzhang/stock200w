# 200W

一个适合手机浏览的静态页面，按 Wishlist、纳指 100 和标普 500 三个股票池查看股价与 200 周均线的距离。

## 工作方式

- 行情来自 Alpha Vantage `TIME_SERIES_WEEKLY_ADJUSTED`。
- 距离按 `(最新复权周收盘价 / 200 周均线 - 1) × 100%` 计算。
- 正常扫描顺序为 Wishlist → 纳指 100 → 标普 500；跨列表重复的股票只出现一次，扫描游标会在每天的批次之间延续。
- `data/blacklist.json` 是三个股票池共享的黑名单。进入黑名单的股票不会被扫描，也不会占用请求 quota。
- 不足 200 周历史的股票会记录预计可重试日期；日期到来前直接跳过且不占 quota，到期后自动重新进入扫描计划。

## 本地设置

复制环境文件并填入 Alpha Vantage key：

```bash
cp .env.local.example .env.local
```

```dotenv
ALPHA_VANTAGE_API_KEY=your_key
DAILY_LIMIT=25
```

运行扫描：

```bash
./scripts/local_update.sh
```

在终端交互运行时，脚本会询问本次是否优先重扫 Wishlist。选择 `y` 后，先扫描 Wishlist，剩余 quota 再从保存的游标继续原计划；同一批次不会重复请求同一只股票。也可以直接传参数：

```bash
./scripts/local_update.sh --rescan-wishlist
```

非交互运行默认不重扫 Wishlist，继续原计划。单个 Alpha Vantage key 每批最多使用 25 次请求；`DAILY_LIMIT` 可以把本次批次设得更小。

## 本地预览

```bash
python3 -m http.server 8000
```

打开 <http://localhost:8000>。首页是 Wishlist，第二个 tab 是纳指 100，第三个 tab 是标普 500；Wishlist 卡片会同时标注它是否属于这两个指数。

## 列表文件

- `data/watchlist.json`：Wishlist 股票代码数组，允许放入两个指数之外的股票。
- `data/blacklist.json`：共享黑名单股票代码数组。
- `data/nasdaq100.json`：纳指 100 的 `[代码, 名称]` 快照。
- `data/sp500.json`：标普 500 的 `[代码, 名称]` 快照。

Wishlist 和黑名单示例：

```json
["AAPL", "MSFT"]
```

更新标普 500 快照时，先下载成分股页面，再运行：

```bash
python3 scripts/update_sp500.py /path/to/downloaded-page.html
```

## GitHub Pages 发布

扫描完成后提交 `data/stocks.json`、`data/update-state.json` 和相关列表文件并推送。GitHub Pages 只会收到生成后的行情数据，不会收到 `.env.local` 或 API key。

页面每 30 秒检查一次 `version.json`；新版本部署完成后，已打开的页面会自动刷新。仅供研究，不构成投资建议。
