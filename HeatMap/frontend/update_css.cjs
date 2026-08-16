const fs = require('fs');
let css = fs.readFileSync('src/index.css', 'utf8');

// Re-apply the specific CSS overrides from earlier
css = css.replace('.stat-card {\n  background: var(--gradient-card);\n  backdrop-filter: blur(8px);\n  border: 1px solid var(--color-border);\n  border-radius: var(--radius-md);\n  padding: 20px;', 
'.stat-card {\n  background: var(--gradient-card);\n  backdrop-filter: blur(8px);\n  border: 1px solid var(--color-border);\n  border-radius: var(--radius-md);\n  padding: 12px 16px;');

css = css.replace('.stat-card-icon {\n  width: 40px;\n  height: 40px;', 
'.stat-card-icon {\n  width: 32px;\n  height: 32px;');

css = css.replace('.stat-card-value {\n  font-size: 28px;', 
'.stat-card-value {\n  font-size: 20px;');

css = css.replace('.leaflet-map {\n  height: 480px;', 
'.leaflet-map {\n  height: 65vh;\n  min-height: 480px;');

css = css.replace('max-height: calc(480px + 90px);', 
'max-height: calc(65vh + 90px);');

// Now apply the global font-size scale modifier
css = css.replace(/font-size:\s*(\d+)px/g, 'font-size: calc($1px * var(--text-scale, 1))');

fs.writeFileSync('src/index.css', css);
console.log('CSS updated successfully');
