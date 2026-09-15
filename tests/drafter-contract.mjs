import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { test } from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const upstream = process.argv[2] && path.resolve(process.argv[2]);
const python = process.argv[3] || process.env.PYTHON || 'python';
const pin = '34d80673e067bdc0c24568d3af899c216adcfaa9';
assert.ok(upstream, 'Usage: node tests/drafter-contract.mjs UPSTREAM_CHECKOUT [PYTHON_EXECUTABLE]');
assert.ok(Number(process.versions.node.split('.')[0]) >= 24, 'Node.js 24+ is required');

function run(executable, args, options = {}) {
  const result = spawnSync(executable, args, {
    cwd: root, encoding: 'utf8', timeout: 60_000, ...options,
  });
  assert.ifError(result.error);
  return result;
}

function succeed(result) {
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  return result.stdout.trim();
}

assert.equal(succeed(run('git', ['-C', upstream, 'rev-parse', 'HEAD'])), pin);
assert.equal(succeed(run('git', ['-C', upstream, 'status', '--porcelain', '--untracked-files=no'])), '',
  'Dependency source and lockfile must be unmodified');
const wrapper = readFileSync(path.join(root, '.github', 'workflows', 'release-draft.yml'), 'utf8');
const wrapperPins = [...wrapper.matchAll(/uses:\s*release-drafter\/release-drafter@([0-9a-f]{40})/g)];
assert.ok(wrapperPins.length > 0, 'Reusable wrapper must pin Release Drafter');
for (const match of wrapperPins) assert.equal(match[1], pin);

const load = (relative) => import(pathToFileURL(path.join(upstream, ...relative.split('/'))).href);
const { normalizeFilepath } = await load('src/common/config/normalize-filepath.ts');
const { parseConfigTarget } = await load('src/common/config/parse-config-target.ts');
const { getConfigFileFromFs } = await load('src/common/config/get-config-file-from-fs.ts');
const { configSchema } = await load('src/actions/drafter/config/schemas/config.schema.ts');
const { parseCategories } = await load('src/actions/drafter/config/parse-categories.ts');
const { matchesCategory, filterPullRequestsByPreCategories } =
  await load('src/actions/drafter/common/category-matching.ts');
const { categorizePullRequests } =
  await load('src/actions/drafter/lib/build-release-payload/categorize-pull-requests.ts');
const { resolveVersionKeyIncrement } =
  await load('src/actions/drafter/lib/build-release-payload/resolve-version-increment.ts');

const defaults = {
  major: 'semver:major', minor: 'semver:minor', patch: 'semver:patch',
  skip: 'skip-changelog', feature: 'enhancement', fix: 'bug',
  documentation: 'documentation', dependencies: 'dependencies',
};
const custom = {
  major: 'release:breaking', minor: 'release:feature', patch: 'release:fix',
  skip: 'release:skip', feature: 'kind:feature', fix: 'kind:bug',
  documentation: 'kind:docs', dependencies: 'kind:deps',
};
const titles = {
  breaking: 'Breaking Changes', feature: 'Features', fix: 'Bug Fixes',
  documentation: 'Documentation', dependencies: 'Dependencies', maintenance: 'Maintenance',
};
const context = { repo: { owner: 'contract', repo: 'consumer' }, ref: 'main' };
const pullRequest = (...names) => ({
  title: 'Synthetic change', labels: { nodes: names.map((name) => ({ name })) },
});
const workspace = mkdtempSync(path.join(root, '.drafter-contract-'));
const previousWorkspace = process.env.GITHUB_WORKSPACE;

function write(filename, contents) {
  mkdirSync(path.dirname(filename), { recursive: true });
  writeFileSync(filename, contents, 'utf8');
}

try {
  for (const scenario of ['default', 'uppercase-default', 'uppercase-custom', 'absent-labels']) {
    await test(scenario, async (t) => {
      const directory = path.join(workspace, scenario);
      const consumer = path.join(directory, 'consumer');
      mkdirSync(consumer, { recursive: true });
      process.env.GITHUB_WORKSPACE = directory;
      const git = (...args) => succeed(run('git', args, { cwd: consumer }));
      git('init', '-q', '-b', 'main');
      git('config', 'user.name', 'Dependency contract');
      git('config', 'user.email', 'dependency-contract@example.invalid');
      git('config', 'core.autocrlf', 'false');
      git('config', 'core.hooksPath', '.git/no-hooks');
      git('config', 'commit.gpgsign', 'false');
      const commit = () => {
        git('add', '-A');
        git('commit', '-qm', 'Synthetic consumer');
        return git('rev-parse', 'HEAD');
      };
      const configured = scenario === 'uppercase-custom' ? custom : defaults;
      const actual = Object.fromEntries(Object.entries(configured)
        .map(([key, name]) => [key, scenario.startsWith('uppercase') ? name.toUpperCase() : name]));
      const categoryTitles = scenario === 'uppercase-custom'
        ? { ...titles, breaking: 'Compatibility Changes', documentation: 'Guides' } : titles;
      const configPath = scenario === 'uppercase-custom' ? '.automation/release.json' : '';
      if (configPath) write(path.join(consumer, configPath), JSON.stringify({
        version: 1, labels: configured,
        categories: { breaking: categoryTitles.breaking, documentation: categoryTitles.documentation },
      }));
      const hostile = '{"_extends":"evil/repository","categories":[],"template":"HOSTILE"}';
      write(path.join(consumer, '.github', 'release-drafter.yml'), hostile);
      write(path.join(directory, '.github', 'release-drafter.json'), hostile);
      write(path.join(consumer, 'source.txt'), 'Synthetic source\n');
      const base = commit();
      const note = '### Changed API\n\n' + [
        'Previous behavior', 'New behavior', 'Type of breaking change',
        'Reason for change', 'Recommended action', 'Affected APIs',
      ].map((heading) => `#### ${heading}\n\nConcrete synthetic API behavior.\n\n`).join('');
      write(path.join(consumer, '.changes', '+contract.breaking.md'), note);
      const head = commit();
      if (configPath) write(path.join(consumer, configPath), '{"version":1,"labels":{"major":"untrusted"}}');

      const labelsPath = path.join(directory, 'labels.json');
      const output = path.join(directory, 'release-drafter.json');
      const githubOutput = path.join(directory, 'outputs.txt');
      const labelSnapshot = scenario === 'absent-labels' ? [] :
        Object.values(actual).map((name) => ({ name, color: 'ffffff' }));
      write(labelsPath, JSON.stringify(labelSnapshot));
      const cli = (command, args) => run(python, [
        '-I', path.join(root, 'toolkit', 'run.py'), command,
        '--repo', consumer, '--head', head, '--default-branch', 'main',
        '--config-path', configPath, ...args,
      ], { env: { ...process.env, GITHUB_WORKSPACE: directory, GITHUB_OUTPUT: githubOutput } });
      const policy = (names, selectedHead = head) => {
        const event = path.join(directory, 'event.json');
        write(event, JSON.stringify({ pull_request: {
          base: { sha: base }, head: { sha: selectedHead }, labels: names.map((name) => ({ name })),
        } }));
        return cli('check', ['--event', event]);
      };

      await t.test('trusted Python policy and configuration producer', () => {
        succeed(policy([actual.major]));
        const noFragment = policy([actual.major], base);
        assert.notEqual(noFragment.status, 0);
        assert.match(noFragment.stderr, /must add a new migration fragment/);
        const conflict = policy([actual.major, actual.skip]);
        assert.notEqual(conflict.status, 0);
        assert.match(conflict.stderr, /Breaking-change PRs must not use/);
        succeed(cli('configuration', ['--labels', labelsPath, '--output', output]));
        const outputs = readFileSync(githubOutput, 'utf8').split(/\r?\n/);
        assert.ok(outputs.includes(`patch-label=${actual.patch}`));
        assert.ok(outputs.includes(`documentation-label=${actual.documentation}`));
      });

      const raw = JSON.parse(readFileSync(output, 'utf8'));
      const parsed = configSchema.parse(raw);
      const config = { ...parsed, categories: parseCategories(parsed, parsed) };
      await t.test('actual upstream category matcher and version resolver', () => {
        assert.equal(raw._extends, undefined);
        assert.notEqual(raw.template, 'HOSTILE');
        const locked = JSON.parse(readFileSync(path.join(root, 'toolkit', 'assets', 'release-drafter.json'), 'utf8'));
        if (scenario === 'default' || scenario === 'absent-labels') assert.deepEqual(raw, locked);
        if (scenario === 'uppercase-default') {
          const unresolved = configSchema.parse(locked);
          const oldConfig = { ...unresolved, categories: parseCategories(unresolved, unresolved) };
          assert.equal(resolveVersionKeyIncrement({
            pullRequests: [pullRequest(actual.major)], config: oldConfig,
          }), 'patch');
          const skipped = pullRequest(actual.skip);
          assert.deepEqual(filterPullRequestsByPreCategories([skipped], oldConfig.categories), [skipped]);
        }
        for (const key of ['major', 'minor', 'patch']) {
          const request = pullRequest(actual[key]);
          const resolved = resolveVersionKeyIncrement({ pullRequests: [request], config });
          assert.equal(resolved, key);
        }
        for (const [key, categoryKey] of [
          ['major', 'breaking'], ['feature', 'feature'], ['fix', 'fix'],
          ['documentation', 'documentation'], ['dependencies', 'dependencies'],
        ]) {
          const request = pullRequest(actual[key]);
          const category = config.categories.find((entry) => entry.title === categoryTitles[categoryKey]);
          assert.ok(category, `Missing ${categoryKey} category`);
          assert.equal(matchesCategory(category, request), true);
          const [uncategorized, categorized] = categorizePullRequests({ pullRequests: [request], config });
          assert.deepEqual(uncategorized, []);
          assert.deepEqual(categorized.filter((entry) => entry.pullRequests.length)
            .map((entry) => entry.title), [categoryTitles[categoryKey]]);
        }
        const excluded = pullRequest(actual.major, actual.skip);
        assert.deepEqual(filterPullRequestsByPreCategories([excluded], config.categories), []);
        assert.equal(resolveVersionKeyIncrement({ pullRequests: [excluded, pullRequest(actual.minor)], config }), 'minor');
        const [uncategorized, categorized] = categorizePullRequests({ pullRequests: [excluded], config });
        assert.deepEqual(uncategorized, []);
        assert.ok(categorized.every((entry) => entry.pullRequests.length === 0));
        assert.equal(resolveVersionKeyIncrement({ pullRequests: [pullRequest('unrelated')], config }), 'patch');
      });

      await t.test('workspace-root file reference loads the locked producer output', () => {
        assert.notEqual(process.platform, 'win32',
          'The pinned upstream root-reference loader requires a POSIX runner; run this contract on Linux');
        const oldTarget = parseConfigTarget(`file:${output}`, context);
        const oldLocation = normalizeFilepath(oldTarget);
        assert.notEqual(path.join(directory, oldLocation), output);
        assert.throws(() => getConfigFileFromFs(oldLocation), /Config file not found/);
        const target = parseConfigTarget('file:/release-drafter.json', context);
        assert.equal(target.scheme, 'file');
        const normalized = normalizeFilepath(target);
        assert.equal(normalized, 'release-drafter.json');
        const loaded = getConfigFileFromFs(normalized);
        assert.deepEqual(JSON.parse(loaded), raw);
        const loadedConfig = configSchema.parse(JSON.parse(loaded));
        assert.deepEqual(parseCategories(loadedConfig, loadedConfig), config.categories);
      });

      await t.test('malformed label snapshots cannot produce a config', () => {
        for (const malformed of [{}, ['not-an-object'], [{}], [{ name: 42 }]]) {
          write(labelsPath, JSON.stringify(malformed));
          const rejectedOutput = path.join(directory, 'rejected.json');
          const result = cli('configuration', ['--labels', labelsPath, '--output', rejectedOutput]);
          assert.notEqual(result.status, 0);
          assert.match(result.stderr, /repository label snapshot/i);
          assert.throws(() => readFileSync(rejectedOutput), { code: 'ENOENT' });
        }
      });
    });
  }
} finally {
  if (previousWorkspace === undefined) delete process.env.GITHUB_WORKSPACE;
  else process.env.GITHUB_WORKSPACE = previousWorkspace;
  rmSync(workspace, { recursive: true, force: true });
}
