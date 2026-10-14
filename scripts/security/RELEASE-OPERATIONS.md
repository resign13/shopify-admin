# 受限发布控制器：安装、验收与首次切换

## 边界

本文件是运维准备步骤，不代表线上已安装。CI 仅上传代码归档并调用已安装的固定控制器；不执行归档里的 root 脚本，不改数据库结构，不恢复数据库，不修改 Nginx/SSH 或控制器自身。

本轮固定使用 `browser-cookie-phase1`：附件仍为 legacy，第 6.4 节登录保护关闭。Cookie、CSRF、权限与通用资源控制保持启用。

归档校验使用流式哈希，限制压缩体积、解压总量、成员数及扩展头大小；拒绝符号链接、硬链接、稀疏文件、路径穿越和未列入清单的内容。校验不提取、不执行归档代码，随后仅从 root 密封副本逐文件写入新版本目录。

## 身份与文件

| 身份 | 范围 |
|---|---|
| `gingtto-deploy` | 密钥 SSH、写入 incoming、调用受限 sudo 控制器 |
| `gingtto-build` | 临时 systemd 构建单元，只写该版本的 `.venv`；无业务配置读取权 |
| `gingtto-admin`／`gingtto-store` | 各自后台／商城服务，不写代码或依赖；配置使用各自同名组 |
| `gingtto-maintenance` | 独立元数据清理凭证，不读取应用配置或业务成本 |
| root 运维 | 安装控制器、配置/证书、显式迁移、权限准备及维护窗口批准 |

路径：

- 只读代码／依赖：`/opt/smawell/releases/{admin,store}/版本摘要-随机标识/`。
- 当前指针：`/opt/smawell/current/{admin,store}`，仅 root 原子切换。
- 保留旧前端资源：`/opt/smawell/public-assets/{admin,store}/`。
- 入站归档：`/opt/smawell/incoming/admin-运行号-重试号/release.tar.gz`，部署账号所有，目录 0700、文件 0600。
- root 状态／只读备份：`/var/lib/gingtto-release/`，0700；配置和数据库备份 0600。
- 应用配置：`/etc/gingtto/runtime/admin.env`、`admin.security.env`，root:`gingtto-admin` 0640；商城对应 root:`gingtto-store` 0640。
- 现有 data、uploads 和已有文件不移走；新代码仅建立指向原目录的受控链接。

原部署目录的旧 `.env*` 只供 root 保留/回滚，不授予应用或构建账号读取；尤其不能把含旧高权限数据库凭证的文件继续放在共享应用组里。配置目录及所有父目录不得由部署账号写入。

构建归档在本机显式设为 0600；SFTP/scp 上传后再次由部署账号显式 `chmod 600`，不能依赖另一 SSH 会话的 umask。root intake 拒绝权限或所有权不符的文件。

## 显式安装准备

1. 从已审查的源码安装 `scripts/security/install_release_controller.sh --install`，只准备账号、目录、root 控制器和受限 sudo。已存在账号须核对同名主组及无 sudo/docker 等额外权限。
2. 单独准备四份 runtime 配置。将两端数据库凭证分别设置为已核验的最小权限运行角色；不要沿用旧 schema owner。公共汇率、商品/订单/库存数据不改。
3. 在独立迁移步骤准备增量结构、撤销旧会话；启动及发布控制器不做 DDL。迁移凭证不写入 runtime 文件。
4. 保留恢复会话；安装专用公钥（建议 authorized_keys 使用 `restrict`），核验主机指纹和密钥登录后再安装 SSH Match 配置。
5. **新发布与语音工作流使用四个独立 secrets：`SECURITY_DEPLOY_HOST`、`SECURITY_DEPLOY_USER`、`SECURITY_DEPLOY_SSH_KEY`、`SECURITY_DEPLOY_KNOWN_HOSTS`。** 不覆盖旧 `DEPLOY_*`，防止正在使用的 GitHub 加密只读导出通道失效。
6. 固定本机同步脚本、DPAPI 私钥和每日 04:00 自动化不改。全局 root 密码登录的停用须等部署、语音配置及既有只读导出通道分别验收后进行；本阶段准备脚本不自动停用。

配置分工必须唯一：`admin.env`／`store.env` 保留各自业务与存储配置，语音开关和签名密钥仅放在 `admin.env`；`*.security.env` 保存 PG、DB、APP_ENV 和 SECURITY 配置。移除业务配置中的旧数据库凭证，两个文件不能重复定义同一键，也不能让 security 文件覆盖语音。使用单行、无反斜杠转义的标准 KEY=value；生成的数据库密码及签名密钥使用随机 URL-safe 字符串。禁止 `GUNICORN_CMD_ARGS` 覆盖，GUNICORN_BIND 仅接受该服务固定的本机端口。

服务 drop-in 清除旧 Environment、PassEnvironment 和 UnsetEnvironment；控制器同时核验真实 ExecStart、两份 EnvironmentFile 和 root 所有的旧 `.env*` 权限。配置、服务身份或监听端点不符时，保持当前版本。

## 持久目录及定时任务

- 维护窗口停止两端服务后核对 data、uploads、image-cache 的目录/文件权限；不递归跟随符号链接，不改写文件内容。不在业务仍写入时盲目批量 chown。
- 确认新服务用户读写其必要目录，代码/依赖不可写，且后台和商城均读不到另一端的 runtime 凭证。
- 服务 drop-in 先清除继承的 `ReadWritePaths`，再仅授权本端 data、uploads 和预留私有目录；发布门禁核对实际生效路径，不接受整个 `/opt` 或 `/`。旧上传路径配置如存在，也须匹配已准备的持久目录。
- 切换前以真实应用身份检查目录访问权限、只读代码/配置，以及 image-cache 中现有文件和锁的权限。此门禁只读取元数据，不写入探针文件、不修改文件内容或权限；旧 root 服务留下的不可写缓存锁会使预检失败，应在维护窗口单独处理。
- 两个清理任务均使用 `gingtto-maintenance` 和 `/etc/gingtto/maintenance.env`，该文件 root:gingtto-maintenance 0640；参考 `maintenance.env.example`。脚本直接使用专用凭证，不导入应用 `.env`。先显式准备角色和结构，再安装新版 service，保留既有 timer 时间。
- `provision-security-roles.py` 为清理角色授予六张元数据表的 DELETE 和必要的时间列 SELECT，不读取会话摘要、订单、成本或发布游标。通知事件仅清理七天以前记录，不重置发布顺序。内部快照角色只有 SELECT，不能 nextval；不开放对外 API。
- `verify-security-aux-roles.py --expected-db *_test --prefix *_test` 在独立库验证两种清理、重复运行、业务指纹不变及权限拒绝。本地已通过；生产角色与定时单元仍需维护阶段单独验收。
- root 控制器审计可安装 `gingtto-release.logrotate.example`，每天轮转、保留 90 天；不包含命令输出、密码、Cookie 或请求正文。

## 首次安全切换

1. 完成本地业务、安全、浏览器、Linux 文件权限和备份恢复验收，准备并验收**独立的兼容回滚归档**，放到 `/etc/gingtto/rollback/{admin,store}.tar.gz`，root 0600。
2. 提示用户保存未提交内容。安装维护响应配置并放置 root 管理的 `/etc/gingtto/maintenance`；实际请求确认 API 返回 503、no-store、Retry-After，随后停止两端旧服务。
3. 安装新服务 drop-in（current 路径、独立账号与配置）和 Nginx 的 current/公共资源路径，核验语法及证书；图片虚拟主机和旧上传策略保持原样。
4. 由运维在 `/etc/gingtto/security-cutover-approved` 写入 root 0600 的短期批准：

   ```json
   {"profile":"browser-cookie-phase1","maintenanceAcknowledged":true,"productionChangesApproved":true,"expiresAt":"由运维填写带时区且不超过未来24小时的时间"}
   ```

   这是操作批准，不代替 Cloudflare、数据库或证书的实际验收。
5. 对每端调用 `sudo -n /usr/local/sbin/gingtto-release deploy admin admin-运行号-重试号`（商城使用 store）。控制器在只读归档校验、隔离非 root 构建与真实运行身份预检后，备份并原子切换。
6. 首次切换没有兼容 fallback、两端旧服务仍运行、配置组不独立、服务仍是 root 或预检失败时，不切换。两端健康且线上只读验收通过后，由运维移除维护标记。

## 后续发布、回滚及语音

- 相同归档的网络重试不重启、不重复备份，也不丢弃上一个回滚版本。
- 健康检查失败自动切回已验收的兼容代码；中断留下 pending 状态，下次操作先恢复。SSH 断开不主动中止已开始的受限操作。
- `rollback admin`／`rollback store` 仅选择 root 状态里的上一兼容版本；保留新增表、文件和备份，不恢复旧会话，不覆盖新订单/库存。
- `voice enable/disable 音频SHA256` 只更改通知投递开关，保留现有签名密钥及其他配置；0640 权限和组不变。重启后从固定服务 MainPID 的进程环境核对实际开关和签名密钥，值不输出；同时以运行身份执行只读脚本及 WAV 检查。重启/检查失败恢复原配置，并检查恢复后的加载值。不会更改个人启用状态或补播历史订单。
- 更新 root 控制器自身须重新经过独立运维审查，应用发布账号没有此权限。

## 本地证据与尚需线上验证

Windows 状态机测试使用明确适配器；隔离 Linux 容器使用真实 UID、权限、fd-relative intake、原子指针、不可写代码、凭证隔离及回滚。容器没有真实 systemd 管理器，其命令契约另行测试，不当作线上单元已运行的证明。

`test_runtime.Dockerfile` 只安装测试工具。`test_install_runtime_linux.py` 在无网络容器中实际重复安装控制器，使用真实 sshd、公钥、严格主机指纹、SFTP 和 sudo 验证专用账号及 root 权限边界；同时用真实 `systemd-analyze verify` 检查六个 service/timer 及应用 drop-in。可执行标记仅供解析器使用，不代表应用、依赖构建或 systemd 管理器已在生产运行。CI 的镜像构建阶段使用 HTTPS Debian 源和原有签名密钥，验收运行阶段禁止网络且不挂载宿主数据或 Docker socket。

Linux 夹具的 `--cap-add SYS_PTRACE` 仅用于在独立 PID 命名空间内读取真实非 root 测试子进程的环境。容器无网络、不挂载宿主进程、凭证或 Docker socket；它不是生产服务权限，也不是 privileged 容器。

原生备份演练通过 `verify_native_restore.py --isolated-fixture --report 新文件` 创建专属 PostgreSQL 16 容器，端口仅发布到本机、仅使用随机命名的两个 `*_test` 库。真实 pg_dump 自定义归档、目录检查及 pg_restore 已验证 45 张表和 24 个序列一致，源库不变，恢复后清除克隆会话，最后只删除标记匹配的测试容器。文件内容恢复另由既有 `verify-security-restore.py` 验证；两者均不恢复到生产或本地同步库。

实际 systemd 单元、依赖构建、源站限制、Full(strict)、GitHub 新密钥和原只读导出通道，均须在获准的生产准备/维护阶段验收。未完成前不宣称已上线。
