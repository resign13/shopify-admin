# Admin Project

目录结构：
- `frontend`：后台管理 Vue 3 项目
- `admin-backend`：后台管理 Flask 后端
- `db/postgres/init_lumiere_admin.sql`：PostgreSQL 初始化脚本
- `docs/api.md`：接口文档

当前架构：
- 后端主数据源已经切换为 PostgreSQL
- 不再使用 `admin-backend/data/*.json` 作为业务数据源
- 后台后端依赖存放在 `admin-backend/_vendor`

数据库默认配置：
- 数据库：`lumiere_admin`
- 主机：`127.0.0.1`
- 端口：`5432`
- 用户：`postgres`

环境变量：
- `LUMIERE_SERVICE_TOKEN=lumiere-service-token`
- `PGPASSWORD=你的 PostgreSQL postgres 用户密码`
- 可选：
  `PGHOST=127.0.0.1`
  `PGPORT=5432`
  `PGDATABASE=lumiere_admin`
  `PGUSER=postgres`

启动后端：
```powershell
cd admin-backend
$env:PGPASSWORD='你的数据库密码'
python app.py
```

启动前端：
```powershell
cd frontend
npm install
npm run dev
```

访问地址：
- 后端：`http://127.0.0.1:5002`
- 前端：`http://localhost:5174`

## GitHub 自动部署

推送 `main` 或手动运行 `.github/workflows/deploy.yml` 会在 GitHub runner
使用 Node.js 22 构建前端，然后上传代码包到服务器并重启 `smawell-admin-api`。
生产目录为 `/opt/smawell/shopify-admin`，采用 Nginx、systemd 和 PostgreSQL。

仓库 Secrets：`DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_PASSWORD`、
`DEPLOY_FINGERPRINT`（SSH SHA256 主机指纹）。当前部署主机为 `47.82.147.236`。

部署包排除 `.env`、虚拟环境、上传目录和运行数据。服务器需预先具备
Python 虚拟环境、rsync、生产配置和对应 systemd 服务。
每次部署会备份代码、配置及数据库到 `/opt/smawell/backups/actions-*`，
并通过共享锁串行执行商城和后台更新。部署失败恢复代码并重启服务，
数据库新增字段保留，不自动恢复数据库备份以免覆盖新业务数据。
前端构建失败时不会修改服务器。
