const $=s=>document.querySelector(s);
// only same-site relative paths (blocks //evil.example and javascript: open-redirect/XSS)
// next= is only ever an app page from a fixed allowlist. The value is decoded repeatedly and dot segments are refused, so
// '/..//evil.com', '/%2e%2e//', '/ui/..//', '/.%2F/' and encoded or control-character tricks all fall back to /ui.
// The part after # (a screen inside the app, e.g. #review/64) is kept when it only contains safe characters.
const SAFE_PATHS=['/ui','/privacy'];
const nextUrl=()=>{let n=new URLSearchParams(location.search).get('next')||'';
  if(n.indexOf('#')<0&&location.hash)n+=location.hash;           // ?next=/ui#review/64 arrives with the # on this page's URL
  const i=n.indexOf('#'),path=i<0?n:n.slice(0,i),hash=i<0?'':n.slice(i);
  let p=path;for(let k=0;k<4;k++){let d;try{d=decodeURIComponent(p)}catch(e){return '/ui'}if(d===p)break;p=d}
  if(!SAFE_PATHS.includes(p))return '/ui';
  return p+(/^#[A-Za-z0-9\/_?=&.%-]*$/.test(hash)&&!/\.\.|\/\//.test(hash)?hash:'')};
(async()=>{
  const s=await (await fetch('/api/auth/state')).json();
  if(s.user){   // don't silently continue as whoever this browser is signed in as
    $('#h').textContent='Already signed in';
    $('#lead').textContent='This browser is signed in as '+s.user.display+' ('+s.user.initials+'). Everyone using this browser shares that sign-in.';
    $('#f').hidden=true;
    const d=document.createElement('div');d.className='btns';
    const go=document.createElement('a');go.className='btn primary';go.href=nextUrl();go.textContent='Continue as '+s.user.display;
    const sw=document.createElement('button');sw.type='button';sw.className='btn';sw.textContent='Sign out and sign in as someone else';
    sw.onclick=async()=>{await fetch('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':(document.cookie.match(/(?:^|; )gac_csrf=([^;]*)/)||[])[1]||''}});location.reload()};
    d.append(go,' ',sw);$('#f').after(d);go.focus();return}
  if(s.needs_setup){
    $('#h').textContent='First-time setup';$('#lead').textContent='Create the first administrator account. Admins can add the other reviewers.';
    ['#setupOnly','#setupOnly2','#pwHint'].forEach(x=>$(x).hidden=false);$('#go').textContent='Create admin and sign in';
    $('#password').autocomplete='new-password';$('#help').textContent='';
    if(!s.setup_allowed){$('#err').textContent='Setup must be done on the computer running the scanner: open http://localhost:8765 there.';$('#go').disabled=true}
  }
  $('#f').onsubmit=async e=>{
    e.preventDefault();$('#err').textContent='';$('#password').removeAttribute('aria-invalid');const b=$('#go');b.disabled=true;b.setAttribute('aria-busy','true');
    try{
      let url='/api/auth/login',body={username:$('#username').value,password:$('#password').value};
      if(s.needs_setup){
        if($('#password').value!==$('#password2').value){throw new Error('Passwords do not match.')}
        if(!$('#display').value.trim()){throw new Error('Please enter your name.')}
        url='/api/auth/setup';Object.assign(body,{display:$('#display').value,initials:$('#initials').value});
      }
      const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const j=await r.json();if(!r.ok)throw new Error(j.error||'Sign-in failed');
      location.href=nextUrl();
    }catch(x){$('#err').textContent=x.message;$('#password').setAttribute('aria-invalid','true');$('#password').select();b.disabled=false;b.removeAttribute('aria-busy')}
  };
  $('#username').focus();
})();
