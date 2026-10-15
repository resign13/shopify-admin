<template>
  <ElDialog v-model="visible" :title="`统一改价 · ${currency}`" width="min(820px, 96vw)" :close-on-click-modal="false" class="order-pricing-dialog">
    <p class="pricing-caption">仅修改本单成交价；整行设置覆盖该颜色全部尺码，可展开分别调整。</p>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" />
    <div class="pricing-table-scroll"><ElTable ref="table" :data="groups" row-key="productId" size="small" empty-text="暂无商品">
      <ElTableColumn type="expand" width="34"><template #default="{row}"><div class="size-prices">
        <label v-for="line in row.lines" :key="line.sizeCode"><span>{{ line.sizeCode }}</span>
          <ElInputNumber :model-value="line.unitPrice" :min="0" :max="9999999999.99" :precision="2" :controls="false" :aria-label="`${row.sku} ${line.sizeCode} 单价`" @update:model-value="value=>setPrice(line,value)" />
          <small>目录参考 USD {{ reference(line) }}</small>
        </label>
      </div></template></ElTableColumn>
      <ElTableColumn prop="sku" label="颜色 SKU" min-width="145" />
      <ElTableColumn :label="`统一单价 ${currency}`" min-width="175"><template #default="{row}">
        <ElInputNumber :model-value="uniformPrice(row)" :min="0" :max="9999999999.99" :precision="2" :controls="false" :placeholder="uniformPrice(row)==null?'分尺码定价':'填写单价'" :aria-label="`${row.sku} 统一单价`" @update:model-value="value=>row.lines.forEach(line=>setPrice(line,value))" />
        <small class="reference-price">目录参考 USD {{ referenceRange(row) }}</small>
      </template></ElTableColumn>
      <ElTableColumn label="操作" min-width="170"><template #default="{row}">
        <ElButton link type="primary" size="small" @click="table?.toggleRowExpansion(row)">按尺码设置</ElButton><ElButton link size="small" @click="restore(row)">恢复当前售价</ElButton>
      </template></ElTableColumn>
    </ElTable></div>
    <template #footer><ElButton @click="visible=false">取消</ElButton><ElButton type="primary" @click="apply">确认应用</ElButton></template>
  </ElDialog>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import { catalogQuote, validAmount } from '../utils/orderPricing';
import { money } from '../composables/workbench';
const props = defineProps({ open:Boolean, items:Array, products:Object, currency:String, exchangeRate:[Number,String] });
const emit = defineEmits(['update:open','apply']);
const visible = computed({get:()=>props.open,set:value=>emit('update:open',value)});
const lines=ref([]), error=ref(''), table=ref();
const groups=computed(()=>{
  const map=new Map();
  for(const line of lines.value){if(!map.has(line.productId))map.set(line.productId,{productId:line.productId,sku:line.sku,lines:[]});map.get(line.productId).lines.push(line);}
  return [...map.values()];
});
watch(()=>props.open,open=>{if(!open)return;error.value='';lines.value=JSON.parse(JSON.stringify(props.items));
  try { for(const id of new Set(lines.value.map(line=>line.productId))){
    for(const size of props.products[id]?.sizePrices||[]){if(!lines.value.some(line=>line.productId===id&&line.sizeCode===size.sizeCode)){
      lines.value.push({productId:id,sku:props.products[id].sku,productName:'',sizeCode:size.sizeCode,quantity:0,...catalogQuote(size.price,props.currency,props.exchangeRate)});
    }}
  }}catch(e){error.value=e.message;}
});
function uniformPrice(row){const prices=new Set(row.lines.map(line=>line.unitPrice));return prices.size===1?row.lines[0].unitPrice:undefined;}
function setPrice(line,value){Object.assign(line,{unitPrice:value,priceSource:'manual',preserveQuote:false,conversionBase:undefined,catalogPriceChanged:false});}
function current(line){return props.products[line.productId]?.sizePrices?.find(size=>size.sizeCode===line.sizeCode)?.price;}
function reference(line){const usd=current(line);return usd==null?'—':money(usd,'USD');}
function referenceRange(row){const values=row.lines.map(current).filter(value=>value!=null);if(!values.length)return '—';const lo=Math.min(...values),hi=Math.max(...values);return lo===hi?money(lo,'USD'):`${money(lo,'USD')} – ${money(hi,'USD')}`;}
function restore(row){try{for(const line of row.lines){const usd=current(line);if(usd==null)throw new Error('原尺码已移除，保留成交价或手工调整');Object.assign(line,catalogQuote(usd,props.currency,props.exchangeRate),{conversionBase:undefined,catalogPriceChanged:false});}error.value='';}catch(e){error.value=e.message;}}
function apply(){if(lines.value.some(line=>!validAmount(line.unitPrice))){error.value='请填写非负单价，最多两位小数；空白不是零价';return;}emit('apply',lines.value);visible.value=false;}
</script>
<style scoped>
.pricing-caption,.size-hint,.reference-price,.size-prices small{font-size:11px;color:#718096;line-height:1.6}.pricing-caption{margin:0 0 14px}.pricing-table-scroll{overflow-x:auto}.reference-price,.size-hint{display:block;margin:4px 0}.size-prices{display:flex;gap:14px;flex-wrap:wrap;padding:12px 18px}.size-prices label{display:flex;flex-direction:column;gap:6px;font-size:12px}.size-prices .el-input-number{width:130px}.pricing-table-scroll :deep(.el-input-number){max-width:145px;width:100%}
</style>
