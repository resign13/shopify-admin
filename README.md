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
