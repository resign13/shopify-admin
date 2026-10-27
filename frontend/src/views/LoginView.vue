<template>
  <div v-if="isPhone" class="mobile-login-view" data-testid="mobile-login">
    <div class="ml-brand"><span>G</span><strong>GINGTTO<small>BUSINESS CONSOLE</small></strong></div>
    <div class="ml-orbit" aria-hidden="true"><i/><i/><span><ElIcon><Collection /></ElIcon></span></div>
    <div class="ml-heading"><p>每一份专注，都值得更好的工具</p><h1>欢迎回来<span>。</span></h1><small>登录你的工作账号，继续今天的业务。</small></div>
    <ElForm :model="form" label-position="top" class="ml-form" @submit.prevent="login"><ElFormItem label="工作账号 / 邮箱"><ElInput v-model.trim="form.email" placeholder="请输入工作账号" autocomplete="username" size="large" aria-label="账号 / 邮箱"><template #prefix><ElIcon><User /></ElIcon></template></ElInput></ElFormItem><ElFormItem label="密码"><ElInput v-model="form.password" type="password" show-password placeholder="请输入密码" autocomplete="current-password" size="large" aria-label="密码"><template #prefix><ElIcon><Key /></ElIcon></template></ElInput></ElFormItem><ElFormItem v-if="captchaRequired" label="图形验证码"><div class="captcha-row"><ElInput v-model.trim="form.captchaCode" placeholder="输入图中字符" maxlength="5" autocomplete="off" aria-label="图形验证码" size="large" @keyup.enter="login"/><button class="captcha-image" type="button" :disabled="captchaLoading||auth.loading" aria-label="刷新图形验证码" @click="loadCaptcha"><img v-if="captchaImage&&!captchaLoading" :src="captchaImage" alt="图形验证码图片"/><span v-else>{{ captchaLoading?'加载中…':'点击重试' }}</span></button></div><span class="captcha-hint">不区分大小写，点击图片刷新</span></ElFormItem><ElAlert v-if="captchaError||auth.error" :title="captchaError||auth.error" type="error" :closable="false"/><ElButton v-if="captchaError" text @click="loadCaptcha">重试加载验证码</ElButton><ElButton class="ml-submit" type="primary" native-type="submit" :loading="auth.loading" :disabled="captchaLoading||!captchaReady">登录工作台<ElIcon><ArrowRight /></ElIcon></ElButton><ElButton v-if="auth.sessionId&&!auth.isAuthenticated" class="ml-retry" :loading="retrying" @click="retryConnection">重试连接</ElButton></ElForm>
    <p class="ml-help">账号由管理员分配<br/>需要帮助？请联系你的管理员</p><footer>GINGTTO · 管理工作台</footer>
  </div>
  <template v-else>
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
</template>
<script setup>
import {useResponsive} from "../composables/responsive";
import {Collection,User,Key,ArrowRight} from "@element-plus/icons-vue";
const {isPhone}=useResponsive();
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

<style scoped>
@media(max-width:767px){.mobile-login-view{min-height:100dvh;background:#f5f7fb;color:#182b49;padding:calc(34px + env(safe-area-inset-top)) 28px calc(20px + env(safe-area-inset-bottom));display:flex;flex-direction:column}.ml-brand{display:flex;align-items:center;gap:10px;margin-bottom:34px}.ml-brand>span{width:32px;height:32px;border-radius:10px;background:#182b49;color:#fff;display:grid;place-items:center;font-size:21px;font-weight:750}.ml-brand>strong{font-size:12px;font-weight:750;letter-spacing:.12em}.ml-brand small{font-size:7px;letter-spacing:.15em;color:#a6b1c3;display:block;font-weight:500;margin-top:2px}.ml-orbit{height:100px;position:relative;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-bottom:28px}.ml-orbit>i{position:absolute;width:143px;height:100px;border-radius:50%;border:1px solid #e3eaf7;transform:rotate(-25deg)}.ml-orbit>i:nth-child(2){width:176px;height:85px;transform:rotate(24deg);border-color:#e9eef8}.ml-orbit>span{width:60px;height:60px;border:1px solid #e6edf9;border-radius:21px;display:grid;place-items:center;background:linear-gradient(145deg,#fff,#eaf1fd);color:#7699db;box-shadow:0 7px 24px #325da408;transform:rotate(-8deg)}.ml-orbit .el-icon{font-size:29px;transform:rotate(8deg)}.ml-heading>p{font-size:11px;color:#a0adc2;letter-spacing:.04em;margin:0 0 9px}.ml-heading h1{font-size:30px;font-weight:700;letter-spacing:-.055em;line-height:1.3;margin:0}.ml-heading h1 span{color:#2f69eb}.ml-heading>small{font-size:11px;color:#98a7be;display:block;margin-top:10px;line-height:1.8}.ml-form{margin-top:28px}.ml-form :deep(.el-form-item){margin-bottom:20px}.ml-form :deep(.el-form-item__label){font-size:11px;color:#7f91ac;line-height:1.6;margin-bottom:8px}.ml-form :deep(.el-input__wrapper){min-height:48px;border:1px solid #e6ebf4;border-radius:12px;box-shadow:none;padding:0 14px;background:#fff}.ml-form :deep(.el-input__inner){font-size:13px;color:#536e95}.ml-form :deep(.el-input__inner::placeholder){font-size:12px;color:#b6c0d0}.ml-form :deep(.el-input__prefix-inner){color:#a9b8cf}.ml-submit{width:100%;height:47px;display:flex;gap:14px;border-radius:12px;font-size:13px;font-weight:550;box-shadow:0 7px 16px #2f69eb16;margin-top:10px}.ml-retry{width:100%;margin:12px 0 0!important;border-radius:12px;min-height:44px}.ml-help{text-align:center;color:#a9b5c8;font-size:11px;line-height:1.9;margin:23px 0 27px}.mobile-login-view footer{text-align:center;color:#bec7d6;font-size:9px;letter-spacing:.12em;margin:auto 0 0;padding-top:10px}.mobile-login-view .captcha-image{width:122px;height:46px;border-radius:11px}.mobile-login-view .captcha-hint{font-size:10px;color:#a6b3c8}}
@media(max-width:370px){.mobile-login-view{padding-left:24px;padding-right:24px}.ml-orbit{height:75px;margin-bottom:24px}.ml-brand{margin-bottom:28px}}
</style>
