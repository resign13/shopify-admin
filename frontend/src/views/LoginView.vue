<template>
  <div class="login-page">
    <section class="login-brand">
      <div style="letter-spacing: 4px; font-size: 24px; font-weight: 700">
        GINGTTO
      </div>
      <div>
        <div class="eyebrow">BUSINESS CONSOLE</div>
        <h1>让每一次决策，<br />都有据可依。</h1>
        <p>商品 · 库存 · 订单 · 经营分析<br />专注业务，协同每一个环节。</p>
      </div>
      <small>GINGTTO 管理工作台</small>
    </section>
    <section class="login-main">
      <div class="login-card">
        <h1>欢迎回来</h1>
        <p>登录您的工作账号，继续管理业务。</p>
        <ElForm :model="form" label-position="top" @submit.prevent="login"
          ><ElFormItem label="账号 / 邮箱"
            ><ElInput
              v-model.trim="form.email"
              placeholder="请输入工作账号"
              autocomplete="username"
              size="large" /></ElFormItem
          ><ElFormItem label="密码"
            ><ElInput
              v-model="form.password"
              type="password"
              show-password
              placeholder="请输入密码"
              autocomplete="current-password"
              size="large" /></ElFormItem
          ><ElAlert
            v-if="auth.error"
            :title="auth.error"
            type="error"
            :closable="false"
          /><ElButton
            type="primary"
            native-type="submit"
            :loading="auth.loading"
            size="large"
            style="width: 100%; margin-top: 12px"
            >登录工作台</ElButton
          ></ElForm
        >
        <p class="small-note" style="margin-top: 26px">
          账号由管理员分配。如需帮助，请联系您的管理员。
        </p>
      </div>
    </section>
  </div>
</template>
<script setup>
import { reactive } from "vue";
import { useRouter } from "vue-router";
import { useAdminAuthStore } from "../stores/auth";
const auth = useAdminAuthStore(),
  router = useRouter(),
  form = reactive({ email: "", password: "" });
async function login() {
  if (auth.loading) return;
  if (!form.email || !form.password) {
    auth.error = "请填写账号和密码";
    return;
  }
  if (await auth.login(form)) router.push(auth.defaultRoute);
}
</script>
