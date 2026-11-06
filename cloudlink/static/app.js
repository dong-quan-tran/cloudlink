const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="cloudlink-token"]').content;
let nodes = [];
let busy = false;
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
  $('run-test').disabled = busy || !($('source').value && $('destination').value && $('source').value !== $('destination').value && portValid);
  ['source', 'destination'].forEach((side) => {
    const node = nodes.find((item) => item.instance_id === $(side).value);
    $(`${side}-meta`).textContent = node ? [node.vpc_id, node.subnet_id].filter(Boolean).join(' · ') : '';
  });
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
  $('result-badge').textContent = healthy ? '● LIVE CHECK SUCCEEDED' : '● LIVE CHECK NEEDS ATTENTION';
  $('result-time').textContent = shortTime(result.timestamp);
  $('result-summary').textContent = result.summary;
  const portLabel = result.port ? ` · port ${result.port}` : '';
  $('result-route').textContent = `${result.source_name} → ${result.destination_name} · ${result.address_type} ${result.tested_address} · ${testLabels[result.test_type] || result.test_type}${portLabel}`;
  $('check-label').textContent = testLabels[result.test_type] || 'TEST';
  $('check-status').textContent = result.check?.management_error ? 'Could not start' : result.check?.incomplete ? 'Incomplete' : healthy ? 'Successful' : 'Failed';
  $('check-detail').textContent = result.check?.detail || 'No test detail returned';
  const issue = result.network_analysis?.checks?.find((check) => check.status === 'fail');
  $('result-recommendation').textContent = issue && !healthy
    ? (result.check?.management_error ? `${result.recommendation} Separately, ${issue.label}: ${issue.detail}` : `${issue.label}: ${issue.detail}`)
    : result.recommendation;
  showNetwork(result.network_analysis, healthy);
}

function showNetwork(analysis, liveSucceeded) {
  const labels = {pass: 'Looks correct', fail: 'Issue found', unknown: 'Couldn’t assess', not_required: 'Not needed'};
  $('network-analysis').hidden = false;
  const status = Object.hasOwn(labels, analysis?.status) ? analysis.status : 'unknown';
  $('network-badge').className = `network-status ${status}`;
  $('network-badge').textContent = analysis ? labels[status] : 'No saved snapshot';
  $('network-summary').textContent = analysis?.summary || 'This older result has no saved routing information. Run a new diagnostic to inspect the configuration.';
  if (liveSucceeded && status === 'fail') {
    $('network-summary').textContent += ' The live check succeeded, so these findings may reflect a changed or unmodeled path. Review the evidence before changing anything.';
  }
  const list = $('network-findings');
  list.replaceChildren();
  (analysis?.checks || []).forEach((check) => {
    const card = document.createElement('article'); card.className = 'network-finding';
    const heading = document.createElement('div'); heading.className = 'network-finding-heading';
    const title = document.createElement('h4'); title.textContent = check.label;
    const state = Object.hasOwn(labels, check.status) ? check.status : 'unknown';
    const badge = document.createElement('span'); badge.className = `network-status ${state}`; badge.textContent = labels[state];
    heading.append(title, badge);
    const detail = document.createElement('p'); detail.textContent = check.detail;
    const evidence = document.createElement('dl'); evidence.className = 'network-evidence';
    const rows = check.key === 'peering'
      ? [['Source VPC', check.source_vpc], ['Dest. VPC', check.destination_vpc], ['Connection', check.connections?.map((peer) => `${peer.id} (${peer.state})`).join(', ')]]
      : [['Table', check.table_id], ['Association', check.association], ['Destination', check.destination_ip], ['Match', check.cidr], ['Target', check.target], ['State', check.route_state]];
    rows.forEach(([label, value]) => {
      if (!value) return;
      const term = document.createElement('dt'); term.textContent = label;
      const description = document.createElement('dd'); description.textContent = value;
      evidence.append(term, description);
    });
    card.append(heading, detail, evidence); list.append(card);
  });
  $('network-scope').textContent = analysis?.scope
    ? `${analysis.scope} These findings describe the selected source-to-destination path, not CloudLink’s management SSH connection.` : '';
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
      const row = document.createElement('button'); row.type = 'button'; row.className = 'history-row';
      row.disabled = !test.check;
      row.addEventListener('click', () => {
        showResult(test);
        $('result-title').scrollIntoView({behavior: 'smooth', block: 'start'});
      });
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
  if (sessionStorage.getItem('cloudlink.pendingJob')) {
    await resumeJob();
    return;
  }
  const button = $('run-test');
  busy = true;
  button.disabled = true;
  button.textContent = 'Running diagnostics…';
  showNotice('');
  try {
    const response = await fetch('/api/tests', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CloudLink-Token': token},
      body: JSON.stringify({source_id: $('source').value, destination_id: $('destination').value, address_type: 'private', test_type: $('test-type').value, ...($('test-type').value === 'tcp' ? {port: Number($('tcp-port').value)} : {})}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Test failed.');
    if (response.status === 202) {
      sessionStorage.setItem('cloudlink.pendingJob', data.id);
      await loadHistory();
      await followJob(data.id);
    } else {
      showResult(data);
    }
    await loadHistory();
  } catch (error) { showNotice(error.message); }
  finally { busy = false; button.innerHTML = 'Run diagnostics <span>→</span>'; updateButton(); }
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
      showResult(job);
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
    $('run-test').innerHTML = 'Run diagnostics <span>→</span>';
    updateButton();
    await loadHistory();
  }
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
resumeJob();
