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
          ><ElFormItem v-if="captchaRequired" label="图形验证码">
            <div class="captcha-row">
              <ElInput v-model.trim="form.captchaCode" placeholder="请输入图中字符" maxlength="5"
                autocomplete="off" aria-label="图形验证码" size="large" @keyup.enter="login" />
              <button class="captcha-image" type="button" :disabled="captchaLoading || auth.loading"
                aria-label="刷新图形验证码" title="点击刷新验证码" @click="loadCaptcha">
                <img v-if="captchaImage && !captchaLoading" :src="captchaImage" alt="图形验证码图片" />
                <span v-else>{{ captchaLoading ? '加载中…' : '点击重试' }}</span>
              </button>
            </div>
            <span class="captcha-hint">不区分大小写，点击图片可刷新。</span>
          </ElFormItem
          ><ElAlert v-if="captchaError" :title="captchaError" type="error" :closable="false" />
          <ElButton v-if="captchaError" text @click="loadCaptcha">重试加载验证码</ElButton
          ><ElAlert
            v-if="auth.error"
            :title="auth.error"
            type="error"
            :closable="false"
          /><ElButton
            type="primary"
            native-type="submit"
            :loading="auth.loading"
            :disabled="captchaLoading || !captchaReady"
            size="large"
            style="width: 100%; margin-top: 12px"
            >登录工作台</ElButton
          ></ElForm
        >
        <ElButton v-if="auth.sessionId && !auth.isAuthenticated" style="width:100%; margin-top:12px"
          :loading="retrying" @click="retryConnection">重试连接</ElButton>
        <p class="small-note" style="margin-top: 26px">
          账号由管理员分配。如需帮助，请联系您的管理员。
        </p>
      </div>
    </section>
  </div>
</template>
<script setup>
import { reactive, ref, onMounted, onBeforeUnmount } from "vue";
import { request } from "../api";
import { useRouter } from "vue-router";
import { useAdminAuthStore } from "../stores/auth";
const auth = useAdminAuthStore(),
  router = useRouter(),
  form = reactive({ email: "", password: "", captchaCode: "", captchaToken: "" });
const retrying = ref(false);
const captchaRequired=ref(false),captchaImage=ref(''),captchaLoading=ref(false),captchaReady=ref(false),captchaError=ref('');
let captchaSerial=0;
async function loadCaptcha() {
  const serial=++captchaSerial;captchaLoading.value=true;captchaReady.value=false;captchaError.value='';
  form.captchaCode='';form.captchaToken='';
  try {
    const result=await request('/api/auth/admin/captcha');
    if(serial!==captchaSerial)return;
    captchaRequired.value=result.enabled===true;
    if(captchaRequired.value){
      if(typeof result.captchaToken!=='string'||!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(result.image||''))throw new Error('验证码响应异常，请重试。');
      captchaImage.value=result.image;form.captchaToken=result.captchaToken;
    }else if(result.enabled!==false)throw new Error('验证码配置响应异常，请重试。');
    captchaReady.value=true;
  }catch(error){if(serial===captchaSerial)captchaError.value=error.status===429?`验证码刷新过于频繁，请在 ${error.retryAfter||60} 秒后重试。`:error.message||'验证码加载失败，请重试。';}
  finally{if(serial===captchaSerial)captchaLoading.value=false;}
}
onMounted(loadCaptcha);
onBeforeUnmount(()=>{captchaSerial++;});
async function retryConnection() {
  retrying.value = true;
  try { await auth.initialize(); if (auth.isAuthenticated) router.push(auth.defaultRoute); }
  finally { retrying.value = false; }
}
async function login() {
  if (auth.loading || captchaLoading.value || !captchaReady.value) return;
  if (!form.email || !form.password) {
    auth.error = "请填写账号和密码";
    return;
  }
  if (captchaRequired.value && !form.captchaCode) {auth.error='请填写图形验证码';return;}
  const payload={email:form.email,password:form.password,...(captchaRequired.value?{captchaToken:form.captchaToken,captchaCode:form.captchaCode}:{})};
  if (await auth.login(payload)) router.push(auth.defaultRoute);
  else if(captchaRequired.value)await loadCaptcha();
}
</script>
<style scoped>
.captcha-row{display:flex;align-items:center;gap:10px;width:100%}.captcha-row>.el-input{flex:1;min-width:0}.captcha-image{width:144px;height:42px;padding:0;border:1px solid #dce3ec;border-radius:4px;background:#f4f7fb;cursor:pointer;overflow:hidden;flex-shrink:0}.captcha-image img{width:100%;height:100%;object-fit:contain}.captcha-image span,.captcha-hint{font-size:12px;color:#6b7b90}.captcha-hint{display:block;margin-top:5px}.captcha-image:disabled{cursor:wait;opacity:.7}
@media(max-width:380px){.captcha-image{width:120px}.captcha-row{gap:8px}}
@media(max-width:767px){.login-page{grid-template-columns:minmax(0,1fr);grid-template-rows:auto 1fr}.login-brand{padding:22px 24px}.login-brand>div:nth-child(2),.login-brand>small{display:none}.login-main{padding:32px 20px;align-items:start}.login-card{width:min(360px,100%)}}
</style>
