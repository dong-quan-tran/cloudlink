const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="cloudlink-token"]').content;
let nodes = [];
let busy = false;
let mode = 'live';
const latestResults = {};
const selectedTraffic = {live: 'ping', configuration: 'overview'};
const modeButtons = document.querySelectorAll('[data-mode]');
const testLabels = {overview: 'Path overview', ping: 'Ping', http: 'HTTP', https: 'HTTPS', ssh: 'SSH', tcp: 'Custom TCP'};
const testDescriptions = {
  ping: 'Sends two ICMP echo requests from the source. A failed ping does not prove that other traffic is blocked.',
  http: 'Requests / over HTTP from the source. Any HTTP status means the service responded.',
  https: 'Requests / over HTTPS from the source. This checks TLS connectivity but does not validate the certificate.',
  ssh: 'Checks for an SSH server banner from the source. No login is attempted.',
  tcp: 'Attempts a TCP connection from the source to the specified destination port.',
};

function showNotice(message) {
  const notice = $('notice');
  notice.textContent = message;
  notice.hidden = !message;
}

function label(node) {
  return `${node.name} · ${node.private_ip || 'no private IP'}`;
}

function fillSelect(element, selected) {
  element.replaceChildren();
  const placeholder = new Option(nodes.length ? 'Select an instance' : 'No running lab instances', '');
  element.add(placeholder);
  nodes.forEach((node) => element.add(new Option(label(node), node.instance_id)));
  if (nodes.some((node) => node.instance_id === selected)) element.value = selected;
}

function updateButton() {
  const testType = $('test-type').value;
  const port = Number($('tcp-port').value);
  const portValid = testType !== 'tcp' || ($('tcp-port').value !== '' && Number.isInteger(port) && port >= 1 && port <= 65535);
  $('run-test').disabled = busy || !($('source').value && $('destination').value && $('source').value !== $('destination').value && portValid);
  if (!busy) $('run-test').textContent = mode === 'live' ? 'Run live test →' : 'Review configuration →';
  modeButtons.forEach((button) => { button.disabled = busy; });
  ['source', 'destination'].forEach((side) => {
    const node = nodes.find((item) => item.instance_id === $(side).value);
    $(`${side}-meta`).textContent = node?.availability_zone || '';
  });
}

function updateTestType() {
  const testType = $('test-type').value;
  selectedTraffic[mode] = testType;
  $('port-option').hidden = testType !== 'tcp';
  $('tcp-port').disabled = testType !== 'tcp';
  $('test-description').textContent = mode === 'live' ? testDescriptions[testType] : testType === 'overview'
    ? 'See the routes and firewall rules between these instances. No port is needed.'
    : 'Check whether AWS rules allow this traffic and its reply. No probe is sent.';
  updateButton();
}

function selectMode(nextMode) {
  mode = nextMode;
  const live = mode === 'live';
  modeButtons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.mode === mode)));
  $('overview-option').hidden = live;
  $('overview-option').disabled = live;
  $('traffic-label').textContent = live ? 'TEST TYPE' : 'TRAFFIC TO REVIEW';
  $('test-type').value = selectedTraffic[mode];
  updateTestType();
  renderLatestResult();
}

function showPage() {
  const history = location.hash === '#history';
  $('diagnostics-view').hidden = history;
  $('history-view').hidden = !history;
  $('diagnostics-link').removeAttribute('aria-current');
  $('history-link').removeAttribute('aria-current');
  $(history ? 'history-link' : 'diagnostics-link').setAttribute('aria-current', 'page');
  if (!history && $('saved-result').open) $('saved-result').close();
  window.scrollTo(0, 0);
  if (history) loadHistory();
}

async function loadNodes() {
  const previousSource = $('source').value;
  const previousDestination = $('destination').value;
  try {
    const response = await fetch('/api/instances');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load instances.');
    nodes = data.instances;
    fillSelect($('source'), previousSource || nodes[0]?.instance_id);
    fillSelect($('destination'), previousDestination || nodes[1]?.instance_id);
    updateButton();
    showNotice(nodes.length < 2 ? 'At least two running CloudLink lab instances are needed.' : '');
  } catch (error) {
    nodes = [];
    fillSelect($('source'));
    fillSelect($('destination'));
    updateButton();
    showNotice(error.message);
  }
}

function shortTime(timestamp) {
  return new Date(timestamp).toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
}

function renderLatestResult() {
  const result = latestResults[mode];
  const configuration = mode === 'configuration';
  $('result-title').textContent = configuration ? 'Latest configuration review' : 'Latest live test';
  $('result-empty').querySelector('h3').textContent = configuration ? 'No configuration review yet' : 'No live test yet';
  $('result-empty').querySelector('p').textContent = configuration ? 'Review the network settings to see findings here.' : 'Run a test to see the result here.';
  $('result-empty').hidden = Boolean(result);
  $('result-content').hidden = !result;
  if (result) renderResult($('result-content'), result);
  else $('result-content').replaceChildren();
}

function saveLatestResult(result) {
  latestResults[result.mode === 'configuration' ? 'configuration' : 'live'] = result;
  renderLatestResult();
}

function renderResult(container, result) {
  const view = $('result-template').content.cloneNode(true);
  const field = (name) => view.querySelector(`[data-result="${name}"]`);
  const configuration = result.mode === 'configuration';
  const healthy = result.check?.ok === true;
  const status = configuration ? result.network_analysis?.status || 'unknown' : healthy ? 'pass' : 'fail';
  field('badge').className = `result-badge ${status}`;
  field('badge').textContent = configuration ? 'Configuration only · no probe sent' : healthy ? 'Live test succeeded' : 'Live test needs attention';
  field('time').textContent = shortTime(result.timestamp);
  field('summary').textContent = result.summary;
  const portLabel = result.port ? ` · port ${result.port}` : '';
  field('route').textContent = `${result.source_name} → ${result.destination_name} · ${result.address_type} ${result.tested_address} · ${testLabels[result.test_type] || 'Connectivity'}${portLabel}`;
  field('live').hidden = configuration;
  field('check-label').textContent = testLabels[result.test_type] || 'TEST';
  field('check-status').textContent = result.check?.management_error ? 'Could not start' : result.check?.incomplete ? 'Incomplete' : healthy ? 'Successful' : 'Failed';
  field('check-detail').textContent = result.check?.detail || 'No test detail returned';
  const issue = result.network_analysis?.checks?.find((check) => check.status === 'fail');
  field('recommendation').textContent = issue && !healthy && !result.check?.management_error && !result.check?.incomplete
    ? `${issue.label}: ${issue.detail}` : result.recommendation || '';
  showNetwork(field, result.network_analysis, healthy);
  container.replaceChildren(view);
}

function evidenceList(rows) {
  const evidence = document.createElement('dl');
  evidence.className = 'network-evidence';
  rows.forEach(([label, value]) => {
    if (!value) return;
    const term = document.createElement('dt');
    term.textContent = label;
    const description = document.createElement('dd');
    description.textContent = value;
    evidence.append(term, description);
  });
  return evidence;
}

function showNetwork(field, analysis, liveSucceeded) {
  const labels = {pass: 'Allowed', fail: 'Issue found', unknown: 'Inconclusive', not_required: 'Not needed', review: 'Rules listed'};
  field('network').hidden = !analysis && liveSucceeded;
  if (field('network').hidden) return;
  const status = Object.hasOwn(labels, analysis?.status) ? analysis.status : 'unknown';
  field('network-badge').className = `network-status ${status}`;
  field('network-badge').textContent = analysis ? labels[status] : 'No saved snapshot';
  field('network-summary').textContent = analysis?.summary || 'Run a configuration review to inspect the current network settings.';
  if (liveSucceeded && status === 'fail') {
    field('network-summary').textContent += ' The live check succeeded, so these findings may reflect a changed or unmodeled path. Review the evidence before changing anything.';
  }
  const list = field('network-findings');
  (analysis?.checks || []).forEach((check) => {
    const card = document.createElement('article'); card.className = 'network-finding';
    const heading = document.createElement('div'); heading.className = 'network-finding-heading';
    const title = document.createElement('h4'); title.textContent = check.label;
    const state = Object.hasOwn(labels, check.status) ? check.status : 'unknown';
    const badge = document.createElement('span'); badge.className = `network-status ${state}`; badge.textContent = labels[state];
    heading.append(title, badge);
    const detail = document.createElement('p'); detail.textContent = check.detail;
    const evidence = evidenceList([
      ['Connection', check.connections?.map((peer) => `${peer.name || 'VPC peering connection'} (${peer.state})`).join(', ')],
      ['Table', check.table_name || (check.table_id ? 'Route table' : '')],
      ['Association', check.association],
      ['Destination', check.destination_ip],
      ['Match', check.cidr],
      ['Target', check.target_name || (check.target ? (check.target === 'local' ? 'Local VPC' : 'Route target') : '')],
      ['State', check.route_state],
      ['Resource', check.resource_names?.join(', ')],
    ]);
    const identifiers = evidenceList([
      ['Source VPC ID', check.source_vpc], ['Destination VPC ID', check.destination_vpc],
      ['Peering IDs', check.connections?.map((peer) => peer.id).join(', ')],
      ['Route table ID', check.table_id], ['Subnet ID', check.subnet_id],
      ['Target ID', check.target !== 'local' && check.target],
      ['Resource IDs', check.resources?.join(', ')],
    ]);
    card.append(heading, detail);
    if (evidence.childElementCount) card.append(evidence);
    if (identifiers.childElementCount || check.rules?.length) {
      const details = document.createElement('details');
      details.className = 'rule-details';
      const caption = document.createElement('summary');
      caption.textContent = check.rules?.length ? 'Rules and resource IDs' : 'Resource IDs';
      details.append(caption, identifiers);
      if (check.rules?.length) {
        const entries = document.createElement('ul');
        check.rules.forEach((rule) => {
          const entry = document.createElement('li');
          entry.textContent = rule;
          entries.append(entry);
        });
        details.append(entries);
      }
      card.append(details);
    }
    list.append(card);
  });
  field('network-scope').textContent = analysis?.scope || '';
}

async function loadHistory() {
  try {
    const response = await fetch('/api/history');
    if (!response.ok) throw new Error('History unavailable');
    const data = await response.json();
    const list = $('history-list');
    list.replaceChildren();
    if (!data.tests.length) {
      const empty = document.createElement('div');
      empty.className = 'history-empty';
      empty.textContent = 'No saved diagnostics yet.';
      list.append(empty);
      return;
    }
    data.tests.forEach((test) => {
      const row = document.createElement('button'); row.type = 'button'; row.className = 'history-row';
      row.disabled = !test.check && !(test.mode === 'configuration' && test.network_analysis);
      row.addEventListener('click', () => {
        $('saved-result-title').textContent = test.mode === 'configuration' ? 'Saved configuration review' : 'Saved live test';
        renderResult($('saved-result-content'), test);
        $('saved-result').showModal();
        $('saved-result').scrollTop = 0;
      });
      const info = document.createElement('div');
      const title = document.createElement('strong'); title.textContent = `${test.source_name} → ${test.destination_name}`;
      const time = document.createElement('small'); time.textContent = `${shortTime(test.timestamp)} · ${test.mode === 'configuration' ? 'Configuration' : 'Live test'} · ${testLabels[test.test_type] || 'Connectivity'}`;
      const status = test.network_analysis?.status && test.mode === 'configuration' ? test.network_analysis.status
        : test.check ? (test.check.ok ? 'pass' : 'fail') : 'review';
      const state = document.createElement('span'); state.className = `history-state ${status}`; state.textContent = test.summary;
      info.append(title, time); row.append(info, state); list.append(row);
    });
  } catch {
    const message = document.createElement('div');
    message.className = 'history-empty';
    message.textContent = 'History is temporarily unavailable. Try opening History again.';
    $('history-list').replaceChildren(message);
  }
}

async function runTest(event) {
  event.preventDefault();
  if ($('run-test').disabled) return;
  if (sessionStorage.getItem('cloudlink.pendingJob')) {
    await resumeJob();
    return;
  }
  const button = $('run-test');
  busy = true;
  updateButton();
  button.textContent = 'Running diagnostics…';
  showNotice('');
  try {
    const response = await fetch('/api/tests', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CloudLink-Token': token},
      body: JSON.stringify({mode, source_id: $('source').value, destination_id: $('destination').value, address_type: 'private', test_type: $('test-type').value, ...($('test-type').value === 'tcp' ? {port: Number($('tcp-port').value)} : {})}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Test failed.');
    if (response.status === 202) {
      sessionStorage.setItem('cloudlink.pendingJob', data.id);
      await loadHistory();
      await followJob(data.id);
    } else {
      saveLatestResult(data);
    }
    await loadHistory();
  } catch (error) { showNotice(error.message); }
  finally { busy = false; updateButton(); }
}

async function followJob(id) {
  // The same status URL works through either app server. Preserve it on refresh.
  for (;;) {
    const response = await fetch(`/api/tests/${encodeURIComponent(id)}`);
    const job = await response.json();
    if (!response.ok) {
      if (response.status === 404) sessionStorage.removeItem('cloudlink.pendingJob');
      throw new Error(job.error || 'Could not retrieve the test. Refresh to reconnect.');
    }
    if (job.status === 'completed') {
      sessionStorage.removeItem('cloudlink.pendingJob');
      showNotice('');
      saveLatestResult(job);
      return;
    }
    if (job.status === 'failed') {
      sessionStorage.removeItem('cloudlink.pendingJob');
      throw new Error(job.error || 'This request could not complete. Please retry.');
    }
    const state = job.status === 'running' ? 'Running' : 'Queued';
    $('run-test').textContent = `${state}…`;
    showNotice(`${state}: ${job.source_name} → ${job.destination_name}. You can refresh this page without losing the request.`);
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

async function resumeJob() {
  const id = sessionStorage.getItem('cloudlink.pendingJob');
  if (!id) return;
  busy = true;
  updateButton();
  try { await followJob(id); }
  catch (error) { showNotice(error.message); }
  finally {
    busy = false;
    updateButton();
    await loadHistory();
  }
}

$('source').addEventListener('change', updateButton);
$('destination').addEventListener('change', updateButton);
$('tcp-port').addEventListener('input', updateButton);
$('test-type').addEventListener('change', updateTestType);
$('refresh').addEventListener('click', loadNodes);
$('diagnostic-form').addEventListener('submit', runTest);
modeButtons.forEach((button) => button.addEventListener('click', () => selectMode(button.dataset.mode)));
window.addEventListener('hashchange', showPage);
showPage();
updateTestType();
loadNodes();
resumeJob();
