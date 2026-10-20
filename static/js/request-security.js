/* Apply the rendered session token to same-origin browser mutations. */
(() => {
 const token=document.querySelector('meta[name="csrf-token"]')?.content;
 if(!token)return;
 const original=window.fetch;
 window.fetch=function(input,options={}){
  const url=new URL(input instanceof Request?input.url:input,location.href);
  const method=(options.method||(input instanceof Request?input.method:'GET')).toUpperCase();
  if(url.origin===location.origin&&!['GET','HEAD','OPTIONS'].includes(method)){
   const headers=new Headers(options.headers||(input instanceof Request?input.headers:undefined));headers.set('X-CSRF-Token',token);options={...options,headers};
  }
  return original.call(this,input,options);
 };
 function protect(form){
  if((form.method||'get').toLowerCase()==='get'||new URL(form.action||location.href,location.href).origin!==location.origin)return;
  let input=form.querySelector('input[name="_csrf_token"]');if(!input){input=document.createElement('input');input.type='hidden';input.name='_csrf_token';form.append(input);}input.value=token;
 }
 document.addEventListener('DOMContentLoaded',()=>document.querySelectorAll('form').forEach(protect));
 document.addEventListener('submit',event=>{if(event.target instanceof HTMLFormElement)protect(event.target);},true);
})();
