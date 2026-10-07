// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// The oracle script of oracle_demo: for each case of a directory, a JSON file that names a
// value, it writes a file of the same name in the output directory, holding what JavaScript
// computes from it.
//
// Usage: node cases.mjs <cases-directory> <output-directory>

import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [casesDirectory, outputDirectory] = process.argv.slice(2);
mkdirSync(outputDirectory, { recursive: true });
for (const file of readdirSync(casesDirectory).filter((name) => name.endsWith('.json')).sort()) {
    const { value } = JSON.parse(readFileSync(join(casesDirectory, file), 'utf8'));
    const result = { square: value * value, half: value / 2 };
    writeFileSync(join(outputDirectory, file), `${JSON.stringify(result, null, 4)}\n`);
}
