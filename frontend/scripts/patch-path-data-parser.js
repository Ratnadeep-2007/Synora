const fs = require('fs');
const path = require('path');

function patchParser(filePath) {
  if (!fs.existsSync(filePath)) {
    return;
  }
  let content = fs.readFileSync(filePath, 'utf8');
  let modified = false;

  // 1. Fix isType to guard against undefined token
  if (content.includes('function isType(token, type) {\n    return token.type === type;\n}')) {
    content = content.replace(
      'function isType(token, type) {\n    return token.type === type;\n}',
      'function isType(token, type) {\n    return Boolean(token && token.type === type);\n}'
    );
    modified = true;
  } else if (content.includes('return token.type === type;')) {
    content = content.replace(
      'return token.type === type;',
      'return Boolean(token && token.type === type);'
    );
    modified = true;
  }

  // 2. Fix parsePath to handle empty/undefined tokens safely
  if (content.includes('const tokens = tokenize(d);') && !content.includes('if (!tokens || tokens.length === 0) return segments;')) {
    content = content.replace(
      'const tokens = tokenize(d);',
      'const tokens = tokenize(d || "");\n    if (!tokens || tokens.length === 0) return segments;'
    );
    modified = true;
  }

  // 3. Guard while loop: while (token && !isType(token, EOD))
  if (content.includes('while (!isType(token, EOD)) {')) {
    content = content.replace(
      'while (!isType(token, EOD)) {',
      'while (token && !isType(token, EOD)) {'
    );
    modified = true;
  }

  if (modified) {
    fs.writeFileSync(filePath, content, 'utf8');
    console.log(`[patch-path-data-parser] Successfully patched ${filePath}`);
  } else {
    console.log(`[patch-path-data-parser] Already patched or pattern not found in ${filePath}`);
  }
}

// Patch in both possible node_modules locations
const targets = [
  path.join(__dirname, '..', 'node_modules', 'path-data-parser', 'lib', 'parser.js'),
  path.join(__dirname, '..', '..', 'node_modules', 'path-data-parser', 'lib', 'parser.js'),
];

for (const target of targets) {
  patchParser(target);
}
