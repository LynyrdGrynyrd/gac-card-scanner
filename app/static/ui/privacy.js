fetch('/api/auth/policy').then(r=>r.ok?r.json():null).then(s=>{if(s)document.getElementById('d').textContent=s.image_retention_days})
