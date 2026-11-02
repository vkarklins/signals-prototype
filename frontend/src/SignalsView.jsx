import { useEffect, useState } from 'react';
import './signals.css';

const blank = () => ({name: '', description: '', instruction: '', enabled: false,
  output_schema: '{\n  "type": "object",\n  "properties": {}\n}'});
async function request(path, options = {}) {
  const response = await fetch(`/api/${path}`, { ...options,
    headers: {'Content-Type': 'application/json'}, cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
function TraceLink({url}) {
  return url ? <a href={url} target="_blank" rel="noreferrer">View trace ↗</a> : <span>Trace link not configured</span>;
}
export default function SignalsView({hidden}) {
  const [period, setPeriod] = useState('7d'), [health, setHealth] = useState(null);
  const [tab, setTab] = useState('definitions');
  const [signals, setSignals] = useState([]), [rows, setRows] = useState([]);
  const [draft, setDraft] = useState(blank), [editing, setEditing] = useState(null);
  const [offset, setOffset] = useState(0), [run, setRun] = useState('');
  const [backfillSignal, setBackfillSignal] = useState(''), [since, setSince] = useState('');
  const [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  useEffect(() => {
    if (hidden) return;
    let cancelled = false;
    setLoading(true); setError(''); setRows([]);
    const path = tab === 'health' ? `signal-health?period=${period}` : tab === 'definitions' ? 'signals' : tab === 'runs'
      ? `signal-runs?limit=50&offset=${offset}`
      : `signal-events?limit=50&offset=${offset}${run ? `&run_id=${encodeURIComponent(run)}` : ''}`;
    request(path).then(data => {if (!cancelled) { if (tab === 'health') setHealth(data); else if (tab === 'definitions') setSignals(data); else setRows(data); }})
      .catch(e => {if (!cancelled) setError(e.message);})
      .finally(() => {if (!cancelled) setLoading(false);});
    return () => {cancelled = true;};
  }, [hidden, tab, offset, run, refresh, period]);
  function changeTab(value) {setTab(value); setOffset(0); setRun(''); setNotice('');}
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const payload = {...draft, output_schema: JSON.parse(draft.output_schema)};
      const result = await request(`signals${editing ? `/${editing}` : ''}`, {method: editing ? 'PATCH' : 'POST', body: JSON.stringify(payload)});
      edit(result);
      setNotice(`Saved ${result.name}, version ${result.version}.`); setRefresh(x => x + 1);
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function retry(id) {
    setBusy(true); setError('');
    try {await request(`signal-runs/${id}/retry`, {method: 'POST'}); setNotice('Retry queued. The detection worker will process it.'); setRefresh(x => x + 1);}
    catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function backfill(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const date = new Date(since);
      if (!since || Number.isNaN(date.getTime()) || date > new Date()) throw new Error('Choose a valid start date in the past.');
      const result = await request(`signals/${backfillSignal}/backfill`, {method: 'POST', body: JSON.stringify({since: date.toISOString()})});
      setNotice(result.queued_runs ? `Queued ${result.queued_runs} runs for Signal version ${result.signal_version}. Keep the detection worker running and check Runs for progress.` : 'No new runs queued. No synced turns matched, or this Signal version already has runs for them.');
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  function edit(signal) {
    setEditing(signal.id); setDraft({name: signal.name, description: signal.description,
      instruction: signal.instruction, enabled: signal.enabled, output_schema: JSON.stringify(signal.output_schema, null, 2)});
    setNotice('');
  }
  // Send only editable fields, including after loading a saved response.
  function field(key, value) {setDraft(d => ({...d, [key]: value}));}
  return <main className="page-content signals-page" hidden={hidden}>
    <section className="page-heading"><div><p className="breadcrumb">Observability <span>/</span> Signals</p><h1>Signals</h1><p className="page-description">Define what to look for. Review what happened.</p></div>
      <button className="secondary-button" disabled={loading || busy} onClick={() => setRefresh(x => x + 1)}>Refresh</button></section>
    <div className="signal-tabs" aria-label="Signal views">{['definitions','runs','events','health'].map(t => <button key={t} aria-pressed={tab === t} onClick={() => changeTab(t)}>{t[0].toUpperCase()+t.slice(1)}</button>)}</div>
    {error && <p className="error-message" role="alert">{error}</p>}
    {notice && <p role="status" className="results-notice">{notice}</p>}
    {loading && <p role="status">Loading…</p>}
    {tab === 'health' ? <section aria-label="Signal health">
      <div className="data-toolbar"><label className="filter-control">Reporting period <select value={period} onChange={e => setPeriod(e.target.value)}>
        <option value="24h">Last 24 hours</option><option value="7d">Last 7 days</option><option value="30d">Last 30 days</option><option value="all">All time</option>
      </select></label><span className="split-badge">All versions</span></div>
      <p className="signal-help">All Signal versions, grouped by when analysis was queued. Analysis success rate measures processing reliability, not detection accuracy. Retries update the current run status. Use Refresh to load updates.</p>
      {!loading && !error && health && <>
        <HealthSummary row={health.totals} />
        <section className="results-section">
          <div className="results-toolbar"><div><h2>Signal overview</h2><p>Current analysis status for each Signal</p></div></div>
          <div className="table-scroll"><table className="signal-health-table"><thead><tr>
            {['Signal', 'Completed', 'Queued', 'Running', 'Failed', 'Findings', 'Success rate', 'Last completion'].map(label => <th scope="col" key={label}>{label}</th>)}
          </tr></thead><tbody>
            {!health.signals.length && <tr><td colSpan="8" className="empty-table">No Signals yet. Create one in Definitions.</td></tr>}
            {health.signals.map(row => <tr key={row.id}><td><p className="message-text">{row.name}</p><span className="message-meta">{row.enabled ? 'Enabled' : 'Disabled'}</span></td>
              <td>{row.completed}</td><td>{row.queued}</td><td>{row.running}</td><td>{row.failed}</td><td>{row.findings}</td>
              <td>{successRate(row.success_rate)}</td><td>{row.last_completion ? new Date(row.last_completion).toLocaleString() : '—'}</td>
            </tr>)}
          </tbody></table></div>
        </section>
      </>}
    </section> : tab === 'definitions' ? <>
      <form className="signal-editor" onSubmit={backfill} aria-label="Backfill previous conversations">
        <h2>Analyze previous conversations</h2>
        <p className="signal-help">Backfill synced turns using one Signal’s latest saved version. Existing runs are skipped; earlier results are preserved. Analysis uses paid model calls.</p>
        <label>Signal to backfill<select required value={backfillSignal} disabled={busy || loading} onChange={e => setBackfillSignal(e.target.value)}>
          <option value="">Choose an enabled Signal</option>
          {signals.filter(s => s.enabled).map(s => <option value={s.id} key={s.id}>{s.name} · Version {s.version}</option>)}
        </select></label>
        <label>Synced on or after (your local time)<input type="datetime-local" required value={since} onChange={e => setSince(e.target.value)} /></label>
        <p className="signal-help">Keep the detection worker running. It will process the queued runs without stopping watch mode. Save any definition edits before requesting a backfill.</p>
        <button className="secondary-button" disabled={busy || loading || !signals.some(s => s.enabled && s.id === backfillSignal)}>{busy ? 'Working…' : 'Queue backfill'}</button>
      </form>
      <div className="signal-layout">
      <section aria-label="Saved Signals"><button className="secondary-button" disabled={busy} onClick={() => {setEditing(null); setDraft(blank());}}>New Signal</button>
        {!loading && !error && !signals.length && <p>No Signals yet. Create one to define what to detect.</p>}
        {signals.map(s => <article className="signal-card" key={s.id}><h2>{s.name}</h2><p>{s.description || 'No description'}</p><p>{s.enabled ? 'Enabled' : 'Disabled'} · Version {s.version}</p><button className="secondary-button" disabled={busy} onClick={() => edit(s)}>Edit {s.name}</button></article>)}</section>
      <form className="signal-editor" onSubmit={save}><h2>{editing ? 'Edit Signal' : 'New Signal'}</h2>
        <label>Name<input required value={draft.name} onChange={e => field('name',e.target.value)} /></label>
        <label>Description<textarea value={draft.description} onChange={e => field('description',e.target.value)} /></label>
        <label>Detection instruction<textarea required rows="6" value={draft.instruction} onChange={e => field('instruction',e.target.value)} /></label>
        <label>Custom fields schema<textarea className="schema-input" required rows="9" spellCheck="false" value={draft.output_schema} onChange={e => field('output_schema',e.target.value)} /></label>
        <p className="signal-help">Use a JSON object schema for each event’s custom fields. Editing the instruction or schema creates a new version.</p>
        <label className="signal-checkbox"><input type="checkbox" checked={draft.enabled} onChange={e => field('enabled',e.target.checked)} />Enabled</label>
        <button className="secondary-button" disabled={busy}>{busy ? 'Saving…' : 'Save Signal'}</button>
      </form></div></> : <>
      <section className="results-section">
        <div className="results-toolbar"><div><h2>{tab === 'runs' ? 'Signal runs' : 'Signal events'}</h2><p>Showing up to 50 {tab} per page. Refresh to load updates.</p></div>
          {run && <button className="secondary-button" onClick={() => {setRun(''); setOffset(0);}}>Show all events</button>}
        </div>
        {run && <p className="signal-help signal-run-filter">Events for run {run}</p>}
        <div className="table-scroll"><table className="signal-activity-table"><thead><tr>
          <th scope="col">{tab === 'runs' ? 'Latest user message' : 'Finding'}</th><th scope="col">Signal</th><th scope="col">{tab === 'runs' ? 'Status' : 'Severity'}</th><th scope="col">Created</th><th scope="col">Details</th>
        </tr></thead><tbody>
          {!loading && !error && !rows.length && <tr><td colSpan="5" className="empty-table">No {tab} here yet. Enabled Signals analyze new conversations when the worker is running.</td></tr>}
          {rows.map(row => <tr key={row.id}>
            <td><p className="message-text">{tab === 'runs' ? row.user_message : row.summary}</p>
              {tab === 'events' && <details><summary>View evidence</summary><p>{row.evidence}</p><pre>{JSON.stringify({payload: row.payload, supporting_span_ids: row.supporting_span_ids}, null, 2)}</pre></details>}
              {row.error && <p className="signal-run-error">{row.error}</p>}
            </td>
            <td><p className="message-text">{row.signal_name}</p><span className="message-meta">Version {row.signal_version} · Turn {row.turn_id}</span></td>
            <td><span className={`signal-status status-${row.status || row.severity}`}>{row.status || row.severity}</span></td>
            <td>{new Date(row.created_at).toLocaleString()}</td>
            <td><div className="signal-table-actions">
              {tab === 'runs' && <>{row.status === 'failed' && <button className="context-toggle" disabled={busy} onClick={() => retry(row.id)}>Retry analysis</button>}<button className="context-toggle" onClick={() => {setRun(row.id); setOffset(0); setTab('events');}}>View {row.event_count} events</button></>}
              <TraceLink url={row.laminar_url} />
            </div></td>
          </tr>)}
        </tbody></table></div>
      </section>
      <div className="signal-actions"><button disabled={!offset || loading} onClick={() => setOffset(x => Math.max(0,x-50))}>Previous</button><span>Page {offset/50+1}</span><button disabled={rows.length < 50 || loading} onClick={() => setOffset(x => x+50)}>Next</button></div>
      </>}
  </main>;
}

function successRate(value) {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function HealthSummary({row}) {
  return <>
    <section className="metric-grid" aria-label="Analysis totals">
      <article className="metric-card"><span className="metric-label">Analysis success rate</span><strong className="metric-value">{successRate(row.success_rate)}</strong><span className="metric-note">Successful / finished analyses</span></article>
      <article className="metric-card"><span className="metric-label">Analyses completed</span><strong className="metric-value">{row.completed}</strong><span className="metric-note">Finished without a processing error</span></article>
      <article className="metric-card case-total-card"><span className="metric-label">Findings</span><strong className="metric-value">{row.findings}</strong><span className="metric-note">Issues detected across all Signals</span></article>
    </section>
    <div className="outcome-summary"><span><i className="legend-dot dot-correct" />{row.queued} queued</span><span><i className="legend-dot dot-miss" />{row.running} running</span><span><i className="legend-dot dot-false" />{row.failed} failed</span><span>Last completion: {row.last_completion ? new Date(row.last_completion).toLocaleString() : '—'}</span></div>
  </>;
}
