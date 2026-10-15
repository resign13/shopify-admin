<template>
  <ElDialog v-model="visible" title="确认币种／汇率调整" width="min(700px,96vw)" :close-on-click-modal="false">
    <div class="currency-controls"><label>订单币种<ElSelect v-model="currency" aria-label="调整订单币种"><ElOption label="USD" value="USD"/><ElOption label="CNY" value="CNY"/></ElSelect></label>
      <label>本单汇率 · 1 USD = CNY<ElInputNumber v-model="rate" :precision="6" :min="0.000001" :max="9999999999.99" :controls="false" placeholder="填写汇率" aria-label="调整本单汇率" /></label></div>
    <p class="currency-help">切换币种换算单价及运费；仅调整汇率时保留手工报价、运费及已有订单成交价。不会修改公共汇率。</p>
    <ElAlert v-if="preview.error" :title="preview.error" type="error" :closable="false"/>
    <template v-else><div class="currency-preview"><span>原总额 <b>{{ money(quoteTotal(quote.items,quote.shippingFee),quote.currency) }}</b></span><span>新总额 <b>{{ money(quoteTotal(preview.value.items,preview.value.shippingFee),currency) }}</b></span></div>
      <ElTable :data="preview.value.items.filter(line=>line.quantity>0)" max-height="320" size="small"><ElTableColumn prop="sku" label="颜色 SKU" min-width="130"/><ElTableColumn prop="sizeCode" label="尺码" width="75"/>
        <ElTableColumn label="原单价" min-width="100"><template #default="{row}">{{ money(oldPrice(row),quote.currency) }}</template></ElTableColumn>
        <ElTableColumn label="新单价" min-width="100"><template #default="{row}">{{ money(row.unitPrice,currency) }}</template></ElTableColumn></ElTable>
      <p class="currency-help">运费：{{ money(quote.shippingFee,quote.currency) }} → {{ money(preview.value.shippingFee,currency) }}；单价先保留两位小数，再按数量计算。</p>
    </template>
    <template #footer><ElButton @click="visible=false">取消</ElButton><ElButton type="primary" :disabled="!!preview.error" @click="apply">确认调整</ElButton></template>
  </ElDialog>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import { previewQuoteChange, quoteTotal } from '../utils/orderPricing';
import { money } from '../composables/workbench';
const props=defineProps({open:Boolean,quote:Object,targetCurrency:String,targetRate:[String,Number],existingOrder:Boolean});
const emit=defineEmits(['update:open','apply']);
const visible=computed({get:()=>props.open,set:value=>emit('update:open',value)}),currency=ref('USD'),rate=ref(null);
watch(()=>props.open,open=>{if(open){currency.value=props.targetCurrency||props.quote.currency;rate.value=props.targetRate==null?null:Number(props.targetRate);}});
const preview=computed(()=>{try{return {value:previewQuoteChange(props.quote,currency.value,rate.value,props.existingOrder)};}catch(e){return {error:e.message};}});
function oldPrice(line){return props.quote.items.find(old=>old.productId===line.productId&&old.sizeCode===line.sizeCode)?.unitPrice||0;}
function apply(){if(preview.value.error)return;emit('apply',preview.value.value);visible.value=false;}
</script>
<style scoped>
.currency-controls{display:flex;gap:16px;flex-wrap:wrap}.currency-controls label{display:flex;flex-direction:column;gap:7px;font-size:12px;min-width:150px}.currency-help{font-size:12px;color:#718096;line-height:1.7}.currency-preview{display:flex;gap:24px;flex-wrap:wrap;margin:16px 0}.currency-preview span{font-size:12px;display:flex;gap:10px}.currency-preview b{font-variant-numeric:tabular-nums}
</style>
