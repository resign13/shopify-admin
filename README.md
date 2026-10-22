# GINGTTO 后台

Vue 3 + Flask + PostgreSQL。商城直接访问受限数据库角色，不通过默认服务令牌访问后台；浏览器使用同源 `/api` 与 HttpOnly Cookie，机器 API 使用独立 Key。会话存储在 PostgreSQL，不使用 JSON 会话文件。

## 本地开发

1. 按 `D:/dulizhan/AGENTS.md` 的约定，先运行固定只读同步脚本：
   `D:/Programs/Python314/python.exe D:/dulizhan/shopify-admin/scripts/sync-production-db.py`。
2. 手动页面连接 `127.0.0.1:55439/lumiere_admin`，使用同步来的真实账号。PGUSER、PGPASSWORD 由现有私有本机配置加载，不提交到 Git。
3. 当前功能分支下启动 `admin-backend/app.py`；显式设置 `PGHOST=127.0.0.1`、`PGPORT=55439`、`PGDATABASE=lumiere_admin`，避免继承测试数据库变量。迁移走独立脚本，生产保持 `DB_SCHEMA_AUTO_MIGRATE=0`。
4. `frontend` 目录执行 `npm ci`、`npm run dev`。前端端口 5174，后端默认端口 5002；检查 Vite 代理与本次后端一致。

自动化验证必须显式使用本机独立 `*_test` 库；含 seed/TRUNCATE 的脚本不得连接手动同步库或生产库。

## 发布

现有 GitHub Actions 在 PR 验证，main/手动工作流验证通过后发布。验证任务只构建一次前端；发布任务下载本次工作流的 `verified-frontend` 产物，不重新构建。

沿用 `SECURITY_DEPLOY_HOST`、`SECURITY_DEPLOY_USER`、`SECURITY_DEPLOY_SSH_KEY`、`SECURITY_DEPLOY_KNOWN_HOSTS`；根权限受限发布控制器校验许可、产物、配置和备份后切换。SSH 配置并未因本轮升级修改。

生产源文件、上传目录、会话和配置不进入产物。回滚仅回退兼容代码，不恢复生产数据库。含后端改动的发布仍需维护授权。

详见 `docs/project-stability-upgrade.md`，包含本轮修改、配置额度、监测方式、兼容顺序及未启用事项。
