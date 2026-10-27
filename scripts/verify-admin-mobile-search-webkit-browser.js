async (page) => {
  const base='http://127.0.0.1:5380';
  if(!page.url().startsWith(base+'/')) throw new Error('Isolated fixture required');
  const measurements=[];
  for(const width of [360,393,430]) {
    await page.setViewportSize({width,height:852});
    for(const [route,selector] of [['orders','.responsive-filters'],['inventory','.responsive-filters'],['products','.goods-search']]) {
      await page.goto(base+'/'+route);await page.waitForLoadState('networkidle');
      const input=page.locator(selector+' input').first();await input.focus();
      const m=await input.evaluate(el=>({font:getComputedStyle(el).fontSize,height:el.closest('.el-input__wrapper').getBoundingClientRect().height,
        focusRing:getComputedStyle(el.closest('.el-input__wrapper')).boxShadow,overflow:document.documentElement.scrollWidth>innerWidth+1}));
      if(m.height!==48||m.font!=='16px'||m.focusRing==='none'||m.overflow) throw new Error('WebKit search mismatch '+route+' '+width);
      measurements.push({width,route,...m});
    }
  }
  return {passed:true,browser:'WebKit',checks:measurements.length,measurements};
}
