const http = require('http');
const fs = require('fs');
const path = require('path');
const root = __dirname;
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/portal.html';
  const full = path.join(root, p);
  fs.readFile(full, (err, data) => {
    if (err) { res.writeHead(404); res.end('not found: ' + p); return; }
    const ext = path.extname(full);
    const types = {'.html':'text/html', '.json':'application/json', '.js':'application/javascript', '.css':'text/css', '.png':'image/png', '.jpg':'image/jpeg'};
    res.writeHead(200, {'Content-Type': types[ext] || 'application/octet-stream'});
    res.end(data);
  });
});
server.listen(8080, () => console.log('Serving at http://localhost:8080'));
