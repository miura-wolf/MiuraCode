import fs from "node:fs"

// esbuild (bundled en tsup) no conoce node:sqlite como builtin y reescribe el
// import a un paquete "sqlite" inexistente. Este post-build restaura el
// specifier verbatim para que Node lo resuelva como builtin.
const path = new URL("../dist/index.js", import.meta.url)
let code = fs.readFileSync(path, "utf8")
const fixed = code.replaceAll('from "sqlite"', 'from "node:sqlite"')
if (fixed === code && !code.includes('from "node:sqlite"')) {
	throw new Error("no se encontró el import de sqlite que corregir")
}
fs.writeFileSync(path, fixed)
console.log("fix-sqlite: import node:sqlite restaurado")
