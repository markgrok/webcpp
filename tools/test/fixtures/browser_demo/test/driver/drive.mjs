// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Runs the program --program names, with node when it is the JavaScript Emscripten wrote, and
// exits 0 when it printed ready.

import { spawnSync } from 'node:child_process';

const program = process.argv[process.argv.indexOf('--program') + 1];
const [command, words] = program.endsWith('.js') ? [process.execPath, [program]] : [program, []];
const run = spawnSync(command, words, { encoding: 'utf8' });
process.stdout.write(run.stdout ?? '');
process.stderr.write(run.stderr ?? '');
const ready = run.status === 0 && (run.stdout ?? '').split('\n').includes('ready');
console.log(ready ? 'drive.mjs: the program is ready' : 'drive.mjs: the program is not ready');
process.exit(ready ? 0 : 1);
