const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="cloudlink-token"]').content;
let nodes = [];
const testLabels = {ping: 'PING', http: 'HTTP', https: 'HTTPS', ssh: 'SSH', tcp: 'CUSTOM TCP'};
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
  $('run-test').disabled = !($('source').value && $('destination').value && $('source').value !== $('destination').value && portValid);
}

function updateTestType() {
  const testType = $('test-type').value;
  $('port-option').hidden = testType !== 'tcp';
  $('test-description').textContent = testDescriptions[testType];
  updateButton();
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

function showResult(result) {
  $('result-empty').hidden = true;
  $('result-content').hidden = false;
  const healthy = result.check?.ok === true;
  $('result-badge').className = `result-badge${healthy ? '' : ' warn'}`;
  $('result-badge').textContent = healthy ? '● TEST SUCCEEDED' : '● NEEDS ATTENTION';
  $('result-time').textContent = shortTime(result.timestamp);
  $('result-summary').textContent = result.summary;
  const portLabel = result.port ? ` · port ${result.port}` : '';
  $('result-route').textContent = `${result.source_name} → ${result.destination_name} · ${result.address_type} ${result.tested_address} · ${testLabels[result.test_type] || result.test_type}${portLabel}`;
  $('check-label').textContent = testLabels[result.test_type] || 'TEST';
  $('check-status').textContent = result.check?.management_error ? 'Could not start' : result.check?.incomplete ? 'Incomplete' : healthy ? 'Successful' : 'Failed';
  $('check-detail').textContent = result.check?.detail || 'No test detail returned';
  $('result-recommendation').textContent = result.recommendation;
}

async function loadHistory() {
  try {
    const response = await fetch('/api/history');
    if (!response.ok) throw new Error('History unavailable');
    const data = await response.json();
    const list = $('history');
    list.replaceChildren();
    if (!data.tests.length) {
      const empty = document.createElement('div');
      empty.className = 'history-empty';
      empty.textContent = 'No saved tests yet.';
      list.append(empty);
      return;
    }
    data.tests.forEach((test) => {
      const row = document.createElement('div'); row.className = 'history-row';
      const info = document.createElement('div');
      const title = document.createElement('strong'); title.textContent = `${test.source_name} → ${test.destination_name}`;
      const time = document.createElement('small'); time.textContent = `${shortTime(test.timestamp)} · ${testLabels[test.test_type] || 'LEGACY TEST'} · ${test.address_type} IP`;
      const succeeded = test.check?.ok ?? (test.summary === 'Connected');
      const state = document.createElement('span'); state.className = `history-state${succeeded ? '' : ' warn'}`; state.textContent = test.summary;
      info.append(title, time); row.append(info, state); list.append(row);
    });
  } catch (error) { showNotice(error.message); }
}

async function runTest() {
  const button = $('run-test');
  button.disabled = true;
  button.textContent = 'Running test…';
  showNotice('');
  try {
    const response = await fetch('/api/tests', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CloudLink-Token': token},
      body: JSON.stringify({source_id: $('source').value, destination_id: $('destination').value, address_type: 'private', test_type: $('test-type').value, ...($('test-type').value === 'tcp' ? {port: Number($('tcp-port').value)} : {})}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Test failed.');
    showResult(data);
    await loadHistory();
  } catch (error) { showNotice(error.message); }
  finally { button.innerHTML = 'Run connection test <span>→</span>'; updateButton(); }
}

$('source').addEventListener('change', updateButton);
$('destination').addEventListener('change', updateButton);
$('tcp-port').addEventListener('input', updateButton);
$('test-type').addEventListener('change', updateTestType);
$('refresh').addEventListener('click', loadNodes);
$('run-test').addEventListener('click', runTest);
updateTestType();
loadNodes();
loadHistory();
