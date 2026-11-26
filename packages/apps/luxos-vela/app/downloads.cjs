const fs = require('node:fs');
const path = require('node:path');

function writableDirectory(directory) {
  try {
    const resolved = fs.realpathSync(directory);
    if (!fs.statSync(resolved).isDirectory()) return '';
    fs.accessSync(resolved, fs.constants.W_OK | fs.constants.X_OK);
    return resolved;
  } catch {
    return '';
  }
}

function downloadName(filename) {
  const name = path.basename(filename);
  return name && name !== '.' && name !== '..' ? name : 'download';
}

function reserveDownload(directory, filename) {
  const name = downloadName(filename);
  const extension = path.extname(name);
  const stem = name.slice(0, name.length - extension.length);
  for (let index = 0; index < 1000; index++) {
    const target = path.join(directory, index ? stem + ' (' + index + ')' + extension : name);
    try {
      const fd = fs.openSync(target, 'wx', 0o600);
      try {
        const { dev, ino } = fs.fstatSync(fd);
        return {
          target,
          discard() {
            try {
              const file = fs.lstatSync(target);
              if (file.dev === dev && file.ino === ino && file.size === 0) fs.unlinkSync(target);
            } catch {}
          }
        };
      } finally {
        fs.closeSync(fd);
      }
    } catch (error) {
      if (error.code !== 'EEXIST') return null;
    }
  }
  return null;
}

module.exports = { writableDirectory, downloadName, reserveDownload };
