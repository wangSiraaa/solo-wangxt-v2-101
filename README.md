# 连续出版物登记应用（Serials Registration）

面向图书馆员的连续出版物（期刊）登记系统。核心要解决的问题：

- **一期合刊覆盖多个期号**（如“第7-8期合刊”）；
- **同一期刊的每一期是不同的物理实体**；
- 馆藏系统必须**同时表达这两层关系**：
  书目层“发行了哪些期号”与实体层“这些期号在哪一册上”。

## 设计要点

### 两层模型，绝不混用

| 层 | 模型 | 含义 |
|---|---|---|
| 书目/发行层 | `Serial`、`Issue` | 刊名 + 期号发行记录。只有“是否发行过” |
| 实体/馆藏层 | `Piece`、`PieceIssue`、`BoundVolume`、`BindingEvent` | 物理分册（条码/索取号/位置）、分册↔期号显式关联、装订册、装订流水 |

- `Issue` 的**卷期编号**（`volume`/`issue_no`）与**发行年月**
  （`pub_year`/`pub_month`）分开录入，支持一卷跨多个公历年
  （跨年卷）和出版日期与编号不一致。
- 期号类型：`normal` 普通期、`combined` 合刊期、`ceased` 停刊月份。
- **缺号** = 编号序列里没有 `Issue`，只表示“没有发行记录”，
  系统不会因此把它标成缺藏。
- **缺藏** = 有 `Issue` 但没有 `PieceIssue`（有发行记录、当前无实体）。
- **停刊月份**不占卷、期号，不产生实体预期。

### 合刊：一个实体，多个显式期号关联

- 一个合刊 `Piece` 通过关联表 `PieceIssue` **逐行**关联 2 个
  （或更多）`Issue`，而不是在条码上放一个“7-8”文本字段
  隐式覆盖两个期号。
- 合刊必须**整组入藏**（服务层校验）；
- 数据库约束 `uniq_one_piece_per_issue` 保证**同一期号最多落在
  一个实体分册上**（一期一册），双条码抢同一期号会被 PostgreSQL 拒绝。
- 装订后从合刊覆盖的**任一期号**都能沿
  `Issue → PieceIssue → Piece → BoundVolume` 找到所在册；
- 拆订后各 `Piece` 凭 `location_before_binding` **恢复各自位置**，
  期号关联保持不动，`BindingEvent` 留下完整流水。

## 目录结构

```
backend/                 Django 5 + DRF + PostgreSQL
  serials/models.py      两层领域模型（含 CHECK/UNIQUE 约束）
  serials/services.py    入藏/装订/拆订/定位/时间轴 领域服务
  serials/views.py       REST 视图与 /api/locate/ 定位端点
  serials/tests/         19 个测试（真实 PostgreSQL 约束）
  serials/management/commands/seed_demo.py  演示数据
frontend/                Vue 3 + Vite
  src/components/Timeline.vue          馆员时间轴（期号覆盖+实际位置）
  src/components/IssueRegisterModal.vue 登记普通期/合刊/停刊
  src/components/CheckInModal.vue       入藏（显式逐期关联）
  src/components/BindingModal.vue       装订/拆订
  src/components/LocateModal.vue        按卷期或年月定位
docker-compose.yml       PostgreSQL + backend(gunicorn) + frontend(nginx)
```

## API 摘要

| 方法/路径 | 说明 |
|---|---|
| `GET  /api/serials/{id}/timeline/` | 时间轴：卷格子、缺号、缺藏、停刊月份 |
| `POST /api/issues/` | 登记普通期/停刊月份（编号与年月分开） |
| `POST /api/serials/combined_group/` | 登记两期合刊（两条 Issue 标同一合刊组） |
| `POST /api/serials/{id}/check_in/` | 入藏：`issue_ids[]` 显式关联到一个条码实体 |
| `GET  /api/locate/?serial=&volume=&issue_no=` | 按卷期定位实体/装订册 |
| `GET  /api/locate/?serial=&year=&month=` | 按发行年月定位 |
| `POST /api/bound-volumes/bind/` | 多个散置 Piece 装订为一册 |
| `POST /api/bound-volumes/{id}/unbind/` | 拆订，恢复各自位置 |

定位结果的 `location_kind`：`piece`（散置在藏）、`bound`（在订，
位置随册）、`not_held`（缺藏）、`ceased`（停刊月份）；
无任何发行记录时返回 404 并明确提示“缺号，不自动等于缺藏”。

## 快速开始（Docker）

```bash
cp .env.example .env
docker compose up --build
# 前端 http://localhost:8080 ，API http://localhost:8000/api/
docker compose exec backend python manage.py seed_demo
```

## 本地开发

```bash
# 后端
cd backend
pip install -r requirements.txt
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 POSTGRES_USER=...
python manage.py migrate
python manage.py seed_demo          # 可选：灌入演示数据
python manage.py runserver

# 前端
cd frontend
npm install
npm run dev                         # http://localhost:5173 ，/api 代理到 8000
```

## 验证样例

演示刊《博览月刊》：

- **跨年卷**：第55卷覆盖 2023-07 ~ 2024-06（`pub_years=[2023,2024]`）；
- **停刊月份**：2023-09 暑期休刊（不占期号，不算月份缺口）；
- **两期合刊**：第55卷第7-8期，2024-02 一个实体 `BC-55-78`
  逐行关联两个期号；第55卷装订为 `Q/BL/55-BD` 后，
  从第7期或第8期都定位到该合订本；
- **缺藏**：第55卷第5期（有发行记录、未入藏）；
- **缺号**：第56卷第3期（完全没有发行记录，不进缺藏清单）。

```bash
cd backend && python manage.py test serials   # 19 tests，真实 PostgreSQL
```

测试覆盖：跨年卷识别、停刊月份与月份缺口分离、缺号≠缺藏、
合刊必须整组入藏、一个实体两条显式期号关联、数据库拒绝一期两册、
装订后从任一期号找册、拆订恢复各自位置、禁止重复装订/混刊装订。
