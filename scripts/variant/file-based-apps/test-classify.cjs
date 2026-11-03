'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { fileBasedMarker, discoverProjects, classifyFile } = require('./classify.cjs');

function evaluated(items = [], properties = { TargetFramework: 'net10.0', TargetFrameworks: '' }) {
    return JSON.stringify({ Properties: properties, Items: { Compile: items.map(FullPath => ({ FullPath })) } });
}

async function fixture(t) {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'fba-classify-'));
    t.after(() => {
        assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()));
        assert(path.basename(root).startsWith('fba-classify-'));
        return fs.rm(root, { recursive: true, force: true });
    });
    const nested = path.join(root, 'nested', 'source files');
    await fs.mkdir(nested, { recursive: true });
    const source = path.join(nested, 'app.cs');
    await fs.writeFile(source, 'Console.WriteLine(42);');
    const makeProject = async relative => {
        const project = path.join(root, relative);
        await fs.mkdir(path.dirname(project), { recursive: true });
        await fs.writeFile(project, '<Project />');
        return project;
    };
    // Stop virtual discovery at the fixture's parent: host projects must not
    // affect tests, but traversal itself still reaches the filesystem root.
    const fixtureFs = {
        realpath: fs.realpath,
        readdir: async (directory, options) => {
            const relative = path.relative(root, directory);
            return relative.startsWith('..') || path.isAbsolute(relative) ? [] : fs.readdir(directory, options);
        },
    };
    return { root, nested, source, makeProject, fs: fixtureFs };
}

test('shebang only on the first line, optionally following BOM', () => {
    assert.equal(fileBasedMarker('#!/usr/bin/env dotnet\nConsole.WriteLine(1);'), 'shebang');
    assert.equal(fileBasedMarker('\uFEFF#!/usr/bin/env dotnet\r\n'), 'shebang');
    assert.equal(fileBasedMarker('\n#!/usr/bin/env dotnet'), undefined);
    assert.equal(fileBasedMarker(' // #!/usr/bin/env dotnet'), undefined);
});

test('real #: directives are distinguished from comments and strings', () => {
    assert.equal(fileBasedMarker('  #:package Example@1.0\nConsole.WriteLine(1);'), 'directive');
    assert.equal(fileBasedMarker('/* comment */\n\t#:property TargetFramework=net10.0'), 'directive');
    for (const text of [
        '// #:package Example@1.0\nConsole.WriteLine(1);',
        '/*\n#:package Example@1.0\n*/',
        'var value = "#:package Example@1.0";',
        'var value = @"line one\n#:package Example@1.0\n";',
        'var value = $@"line one\n#:package Example@1.0\n";',
        'var value = @$"line one\n#:package Example@1.0\n";',
        'var value = """\n#:package Example@1.0\n""";',
        'var value = $$"""\n#:package Example@1.0\n""";',
        'var value = """"\n"""\n#:property Anything=true\n"""";',
        'var c = \'"\'; // #:package Example@1.0',
        'var value = @"a ""quoted"" value\n#:package Example@1.0\n";',
    ]) assert.equal(fileBasedMarker(text), undefined, text);
    assert.equal(fileBasedMarker('var value = "escaped \\\" quote";\n#:sdk Microsoft.NET.Sdk.Web'), 'directive');
});

test('explicit markers bypass project discovery and SDK queries', async () => {
    const result = await classifyFile({ filePath: '/not/a/file.cs', text: '#:property X=true',
        fs: { readdir() { throw new Error('Should not inspect projects'); } } });
    assert.equal(result.kind, 'file');
    assert.equal(result.reason, 'directive');
});

test('nested literals inside interpolation cannot expose false directive lines', () => {
    const nestedVerbatim = 'var value = $@"{@"this ""contains""\n#:package Example@1.0\n"}";';
    const nestedRaw = 'var value = $$"""\n{{"""\n#:property Anything=true\n"""}}\n""";';
    const codeInInterpolation = 'var value = $"{new Func<int>(() => {\n/* #:package Example */\nreturn 1;\n})()}";';
    for (const text of [nestedVerbatim, nestedRaw, codeInInterpolation]) {
        assert.equal(fileBasedMarker(text), undefined, text);
        assert.equal(fileBasedMarker(text + '\n#:property RealDirective=true'), 'directive', text);
    }
});

test('no project is a file app, including directories outside a workspace', async t => {
    const f = await fixture(t);
    const result = await classifyFile({ filePath: f.source, text: '', fs: f.fs });
    assert.equal(result.kind, 'file');
    assert.equal(result.reason, 'no-project');
});

test('discovery reaches the filesystem root without a workspace boundary', async () => {
    const source = path.resolve('deep', 'source', 'app.cs');
    const visited = [];
    await discoverProjects(source, { fs: { readdir: async directory => { visited.push(directory); return []; } } });
    assert.equal(visited[0], path.dirname(source));
    assert.equal(visited.at(-1), path.parse(source).root);
    assert.equal(new Set(visited).size, visited.length);
});

test('directory access errors do not imply that no project exists', async () => {
    await assert.rejects(discoverProjects(path.resolve('app.cs'), {
        fs: { readdir: async () => { throw new Error('Access denied'); } },
    }), /Cannot inspect projects.*Access denied/);
});

test('project inclusion wins over nearer excluded projects; evaluates from each project directory', async t => {
    const f = await fixture(t);
    const nearest = await f.makeProject('nested/Excluded.csproj');
    const ancestor = await f.makeProject('Parent.csproj');
    const calls = [];
    const result = await classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async (args, options) => {
            calls.push(args[1]);
            assert.equal(options.cwd, path.dirname(args[1]));
            assert(args.includes('-property:Configuration=Debug'));
            return { stdout: evaluated(args[1] === ancestor ? [f.source] : []), exitCode: 0 };
        } });
    assert.equal(result.kind, 'project');
    assert.equal(result.projectPath, ancestor);
    assert.deepEqual(calls, [nearest, ancestor]);
});

test('multiple projects in the same directory are checked, rather than selecting only the first', async t => {
    const f = await fixture(t);
    await f.makeProject('nested/A.csproj');
    const included = await f.makeProject('nested/B.csproj');
    const result = await classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async args => evaluated(args[1] === included ? [f.source] : []) });
    assert.equal(result.projectPath, included);
});

test('only all successful nonmember evaluations imply exclusion', async t => {
    const f = await fixture(t);
    await f.makeProject('nested/Excluded.csproj');
    const result = await classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async () => evaluated([]) });
    assert.equal(result.kind, 'file');
    assert.equal(result.reason, 'excluded');
    await assert.rejects(classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async () => ({ exitCode: 1, stderr: 'The imported project is missing' }) }), /membership could not be determined/);
    await assert.rejects(classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async () => 'not JSON' }), /MSBuild 17.8/);
});

test('an unresolvable sibling does not prevent positive project inclusion', async t => {
    const f = await fixture(t);
    const broken = await f.makeProject('nested/A.csproj');
    const included = await f.makeProject('nested/B.csproj');
    const result = await classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async args => {
            if (args[1] === broken) throw new Error('Missing SDK');
            return evaluated([f.source]);
        } });
    assert.equal(result.projectPath, included);
});

test('multi-target inner membership is honored even if the outer item list is empty', async t => {
    const f = await fixture(t);
    await f.makeProject('Multi.csproj');
    const queries = [];
    const result = await classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async args => {
            const framework = args.find(value => value.startsWith('-property:TargetFramework='))?.split('=')[1];
            queries.push(framework);
            return evaluated(framework === 'net10.0' ? [f.source] : [], { TargetFramework: framework || '', TargetFrameworks: 'net8.0;net10.0' });
        } });
    assert.equal(result.kind, 'project');
    assert.equal(result.targetFramework, 'net10.0');
    assert.deepEqual(queries, [undefined, 'net8.0', 'net10.0']);
});

test('outer inclusion does not override conditional removal in every real target framework', async t => {
    const f = await fixture(t);
    await f.makeProject('Multi.csproj');
    const result = await classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async args => {
            const inner = args.some(value => value.startsWith('-property:TargetFramework='));
            return evaluated(inner ? [] : [f.source], { TargetFramework: '', TargetFrameworks: 'net8.0;net10.0' });
        } });
    assert.equal(result.kind, 'file');
    assert.equal(result.reason, 'excluded');
});

test('SDK banners do not invalidate a valid evaluated JSON object', async t => {
    const f = await fixture(t);
    const project = await f.makeProject('Project.csproj');
    const result = await classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async () => 'Welcome to .NET\nWarning about a file\n' + evaluated([f.source]) });
    assert.equal(result.projectPath, project);
});

test('project path matching resolves source and Compile item symlinks', async t => {
    const f = await fixture(t);
    const alias = path.join(f.root, 'alias.cs');
    try { await fs.symlink(f.source, alias); }
    catch (error) { if (error.code === 'EPERM') { t.skip('Symlinks require privilege on this host'); return; } throw error; }
    const project = await f.makeProject('Project.csproj');
    const result = await classifyFile({ filePath: f.source, text: '', fs: f.fs,
        runDotnet: async () => evaluated([alias]) });
    assert.equal(result.projectPath, project);
});

test('cancellation never turns uncertain membership into exclusion', async t => {
    const f = await fixture(t);
    const controller = new AbortController();
    controller.abort(new Error('User cancelled'));
    await assert.rejects(classifyFile({ filePath: f.source, text: '', fs: f.fs, signal: controller.signal }), /User cancelled/);
});
