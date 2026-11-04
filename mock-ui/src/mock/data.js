// Shared fake data for the Tripwire mock UI.
//
// Every page reads from this file, so counts and names agree across screens.
// Don't edit it in a page PR: propose changes in their own small PR.
//
// The story (proposed): the Olympic bug, over 7 days.
//   Day 1 (Oct 29): a content update leaves some Olympic trails without a length. The trail
//     lookup tool errors, the assistant gives vague answers, visitors get frustrated.
//   Day 3 (Oct 31): fix 1 (app v1.4.1) stops the error, but the assistant now invents trail
//     lengths. No error anywhere. The custom tripwire "Made-up park facts" catches it (Critical).
//   Day 6 (Nov 3): fix 2 (app v1.4.2) repairs the data; both problems go quiet.
//   Background: sold-out campsites and large-party bookings, so lists don't look staged.
//
// Events, runs, cluster counts and notifications are all generated from the tables below,
// so they can't disagree.
//
// Pages don't import from this file directly. They call useStoryData() (src/components/StoryClock.jsx),
// which returns makeStoryData(asOf): the same helpers, showing only what had happened by the
// story day picked in the header. A page built that way follows the day picker automatically.

export const DAYS = ['2026-10-29', '2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04'];
export const DAY_LABELS = ['Oct 29', 'Oct 30', 'Oct 31', 'Nov 1', 'Nov 2', 'Nov 3', 'Nov 4'];
export const NOW = '2026-11-04T09:30:00';

// The days the header's day picker offers. asOf = the moment the developer looks at Tripwire.
export const STORY_DAYS = [
  { id: 'day1', label: 'Day 1', asOf: '2026-10-29T18:00:00', note: 'Olympic trail lookup starts failing' },
  { id: 'day3', label: 'Day 3', asOf: '2026-10-31T18:00:00', note: 'Fix 1 shipped (v1.4.1); the assistant starts inventing trail lengths' },
  { id: 'day6', label: 'Day 6', asOf: '2026-11-03T18:00:00', note: 'Fix 2 shipped (v1.4.2); both problems quiet' },
  { id: 'today', label: 'Today', asOf: NOW, note: 'The whole week' },
];
export const DEFAULT_STORY_DAY = 'today';

// A notification counts as unread for 48 hours after it arrives (relative to asOf).
const UNREAD_FOR_HOURS = 48;

// App version in production on each day (from trace metadata).
const APP_VERSION_BY_DAY = ['v1.4.0', 'v1.4.0', 'v1.4.1', 'v1.4.1', 'v1.4.1', 'v1.4.2', 'v1.4.2'];

// Traces arriving per day (every tripwire reads these, unless it started later).
const TRACES_PER_DAY = [21, 23, 22, 20, 24, 22, 12];

export const LAMINAR_PROJECT_URL = 'http://localhost:5667/project/demo';

// ---------------------------------------------------------------- tripwires

export const tripwires = [
  {
    id: 'failure-detector', name: 'Failure Detector', kind: 'preset', status: 'active', createdAt: '2026-10-21',
    instruction: 'Find runs where the agent failed to do what the user asked: tool errors it could not recover from, wrong actions, or giving up.',
    payloadFields: [
      { name: 'failure', description: 'What went wrong, in one sentence' },
      { name: 'source', description: 'tool, model, or user input' },
    ],
    triggerFilters: [], sampleRate: 100,
    alerts: { newCluster: true, newCriticalEvent: true, skipSimilar: true, slack: true },
  },
  {
    id: 'friction-detector', name: 'Friction Detector', kind: 'preset', status: 'active', createdAt: '2026-10-21',
    instruction: 'Find turns where the user shows friction: repeating themselves, correcting the assistant, or expressing annoyance.',
    payloadFields: [
      { name: 'friction', description: 'What the user struggled with' },
      { name: 'user_signal', description: 'The words that show it' },
    ],
    triggerFilters: [], sampleRate: 100,
    alerts: { newCluster: true, newCriticalEvent: true, skipSimilar: true, slack: true },
  },
  {
    id: 'intent-classifier', name: 'Intent Classifier', kind: 'preset', status: 'active', createdAt: '2026-10-21',
    instruction: 'What was the user trying to accomplish? Classify the primary intent.',
    payloadFields: [{ name: 'intent', description: 'The primary intent, in a few words' }],
    triggerFilters: [], sampleRate: 100,
    alerts: { newCluster: false, newCriticalEvent: false, skipSimilar: true, slack: false },
  },
  {
    id: 'task-evaluator', name: 'Task Evaluator', kind: 'preset', status: 'active', createdAt: '2026-10-21',
    instruction: 'Did the agent complete the task the user asked for? Record the task and the outcome.',
    payloadFields: [
      { name: 'task', description: 'The task the user asked for' },
      { name: 'outcome', description: 'completed, partly completed, or not completed' },
    ],
    triggerFilters: [], sampleRate: 100,
    alerts: { newCluster: false, newCriticalEvent: false, skipSimilar: true, slack: false },
  },
  {
    id: 'made-up-park-facts', name: 'Made-up park facts', kind: 'custom', status: 'active', createdAt: '2026-10-31',
    instruction: "Find replies that state park facts (trail lengths, hours, fees, amenities) that the tool outputs don't support.",
    payloadFields: [
      { name: 'claim', description: 'The fact the assistant stated' },
      { name: 'evidence', description: 'What the tool output actually said' },
    ],
    triggerFilters: [{ field: 'metadata.app_version', op: 'starts with', value: 'v1.4' }], sampleRate: 100,
    alerts: { newCluster: true, newCriticalEvent: true, skipSimilar: true, slack: true },
  },
];

// Creation presets mirror the approved Laminar template content. They are not live tripwires.
// Source: lmnr-ai/lmnr, frontend/components/signals/prompts.ts (Apache-2.0).
export const tripwireTemplates = [
  {
    "id": "failure",
    "name": "Failure Detector",
    "shortName": "Failure",
    "icon": "alert-circle",
    "description": "Spot errors, loops and wrong tool usage",
    "instruction": "Report every distinct error the agent made in this run that meets the bar below. One finding per distinct error. [IMPORTANT]: If nothing meets the bar, submit no findings. A clean run is a valid outcome, and an unsupported finding is worse than no finding.\n\nReportable:\n1. A wrong action or flawed reasoning step that affected the outcome or wasted substantial work.\n2. A violation of a stated instruction or precondition — from the system prompt, the user's request, or a tool's stated contract. Reportable even if the run continued past it and even if the agent later corrected it. An instruction here is an explicit requirement or prohibition; a description of a typical procedure, a suggestion, or general guidance ('keep changes minimal', 'test your work', 'you may use X') is not one, and departing from it is reportable only under rule 1 by its effect. A violation is a forbidden action the agent actually performed, or a required action or check it never performed; an attempt the environment rejected before it took effect, which the agent then corrected, is a slip under rule 5, not a violation. Formatting or wording deviations count when they are in the final answer or deliverable, or when the instruction states the format is required; the same deviation in intermediate reasoning or scratch output does not.\n3. Repeated near-identical failures (same tool, same arguments, same kind of error) that together consumed a substantial part of the run, even if the agent eventually recovered. Report these as ONE finding: state how many times it happened and cite the spans.\n4. A factual assurance made to the user that no tool result or provided context supports. Unsupported is enough; you do not need an in-trace contradiction for the agent's own claims. This includes an unqualified answer when the trace shows the agent saw conflicting sources, an alternative reading, or an unresolved check that would change it — the missing caveat is the error, whichever option the agent picked — and a claim about every item or the whole set when only a sample was checked.\n\nNot reportable:\n5. A single minor slip the agent corrected within a step or two. Rule 2 overrides this exemption: an instruction violation is reportable even when minor and corrected.\n6. Skipping a planned lookup or verification, when the evidence the agent did gather is sufficient to support its answer. Rule 2 overrides this too: if the skipped step was itself a stated instruction, report it. So does rule 4: if the agent told the user the check was done, or its answer asserts something only the skipped step could establish (completeness of a search, that every item was checked), report it.\n\nGrounding:\n7. Cite the specific spans and quote the decisive evidence for every finding.\n8. The agent's own reasoning is always in scope: flag a conclusion the trace's evidence doesn't support. This requires no external knowledge, only reading the trace.\n9. External facts are different: never declare a result wrong from your own knowledge of the world unless the contradiction is visible in the trace itself. Never assert mechanical details the trace does not literally show — when judging \"substantial\" under rules 1 and 3, count the spans or tool calls you can actually see and cite them.\n10. Never infer environment rules or prerequisites that are not stated. This does not limit rule 4: the agent's assurances still need support.",
    "payloadFields": [
      {
        "name": "description",
        "description": "What went wrong, the decisive evidence with span references, and the impact on the run's outcome",
        "type": "string",
        "choices": []
      }
    ]
  },
  {
    "id": "logic",
    "name": "Logic Analyzer",
    "shortName": "Logic",
    "icon": "brain",
    "description": "Find flaws in reasoning and decision-making",
    "instruction": "Analyze this trace for flaws in the agent's reasoning or decision-making.\nLook for poor planning, contradictions, unnecessary steps, or missed opportunities.",
    "payloadFields": [
      {
        "name": "description",
        "description": "Description of the reasoning flaw or issue",
        "type": "string",
        "choices": []
      },
      {
        "name": "severity",
        "description": "Severity of the logic issue",
        "type": "enum",
        "choices": [
          "low",
          "medium",
          "high"
        ]
      }
    ]
  },
  {
    "id": "task",
    "name": "Task Evaluator",
    "shortName": "Task",
    "icon": "check-circle",
    "description": "Evaluate if the agent completed the user's request",
    "instruction": "Did the agent successfully complete what the user asked for?\nConsider whether the output matches the user's intent and is correct.",
    "payloadFields": [
      {
        "name": "success",
        "description": "Level of task completion",
        "type": "enum",
        "choices": [
          "full",
          "partial",
          "failed"
        ]
      },
      {
        "name": "description",
        "description": "Description of task completion status. If the task was not completed, describe what went wrong.",
        "type": "string",
        "choices": []
      }
    ]
  },
  {
    "id": "friction",
    "name": "Friction Detector",
    "shortName": "User friction",
    "icon": "frown",
    "description": "Identify user frustration and poor UX",
    "instruction": "Analyze this session for signs of user frustration or friction.\nLook for confusion, repeated attempts, or poor user experience.",
    "payloadFields": [
      {
        "name": "description",
        "description": "Description of the friction or frustration observed",
        "type": "string",
        "choices": []
      },
      {
        "name": "severity",
        "description": "Severity of the user friction",
        "type": "enum",
        "choices": [
          "low",
          "medium",
          "high"
        ]
      }
    ]
  },
  {
    "id": "hallucination",
    "name": "Hallucination Detector",
    "shortName": "Hallucination",
    "icon": "cloud-off",
    "description": "Detect made-up facts and incorrect claims",
    "instruction": "Did the agent make up facts, hallucinate information, or confidently\nstate something incorrect? Compare claims against available context.",
    "payloadFields": [
      {
        "name": "description",
        "description": "Description of the hallucination",
        "type": "string",
        "choices": []
      },
      {
        "name": "type",
        "description": "Type of hallucination detected",
        "type": "enum",
        "choices": [
          "factual",
          "contextual",
          "fabrication"
        ]
      }
    ]
  },
  {
    "id": "intent",
    "name": "Intent Classifier",
    "shortName": "Intent",
    "icon": "target",
    "description": "Classify what the user was trying to accomplish",
    "instruction": "What was the user trying to accomplish in this session?\nClassify the primary intent.",
    "payloadFields": [
      {
        "name": "intent",
        "description": "The user's primary intent",
        "type": "string",
        "choices": []
      },
      {
        "name": "complexity",
        "description": "Complexity of the user's request",
        "type": "enum",
        "choices": [
          "simple",
          "moderate",
          "complex"
        ]
      }
    ]
  }
];

// Scripted test results, not an evaluation of the editable instruction.
const tripwireSamples = [
  {
    id: 'sample-trail-error', name: 'Olympic trail lookup failed', time: '2026-10-29T12:00:00',
    visitor: 'I already asked twice: how long is the Olympic trail?',
    reply: 'I cannot find that information. Please try again later.',
    evidence: 'get_park_details returned an error: trail length missing.',
    results: {
      failure: { description: 'The trail lookup failed and the assistant offered no useful next step.' },
      logic: { description: 'The assistant repeated an unhelpful reply instead of recovering from the lookup failure.', severity: 'medium' },
      task: { success: 'failed', description: 'The visitor did not receive the requested trail length.' },
      friction: { description: 'The visitor repeated the same question after two unanswered attempts.', severity: 'high' },
      hallucination: null,
      intent: { intent: 'Find a trail length', complexity: 'simple' },
    },
  },
  {
    id: 'sample-made-up-distance', name: 'Unsupported Olympic trail length', time: '2026-10-31T12:00:00',
    visitor: 'How long is this Olympic trail?', reply: 'The trail is exactly 4.2 miles long.',
    evidence: 'get_park_details returned length: null; no source supplied a distance.',
    results: {
      failure: { description: 'The assistant stated a precise trail length unsupported by the tool output.' },
      logic: { description: 'A missing value was treated as evidence of an exact distance.', severity: 'high' },
      task: { success: 'failed', description: 'The visitor received an unsupported answer.' },
      friction: null,
      hallucination: { description: 'The assistant invented a distance of 4.2 miles.', type: 'fabrication' },
      intent: { intent: 'Find a trail length', complexity: 'simple' },
    },
  },
  {
    id: 'sample-booking-success', name: 'Successful campsite booking', time: '2026-11-03T12:00:00',
    visitor: 'Book a campsite for two people.', reply: 'Your campsite booking is confirmed.',
    evidence: 'book_campsite returned status: confirmed, party_size: 2.',
    results: {
      failure: null, logic: null, friction: null, hallucination: null,
      task: { success: 'full', description: 'The requested campsite was booked for two people.' },
      intent: { intent: 'Book a campsite', complexity: 'simple' },
    },
  },
];

// ---------------------------------------------------------------- clusters (a tree)
// parentId null = top level. Events belong to leaf clusters only.

export const clusters = [
  // Failure Detector
  { id: 'fd-tools', tripwireId: 'failure-detector', parentId: null, name: 'Tool errors' },
  { id: 'fd-olympic', tripwireId: 'failure-detector', parentId: 'fd-tools', name: 'Olympic trail lookup failing',
    summary: 'get_park_details errors for some Olympic trails; the assistant cannot answer trail questions.' },
  { id: 'fd-booking', tripwireId: 'failure-detector', parentId: null, name: 'Booking problems' },
  { id: 'fd-party', tripwireId: 'failure-detector', parentId: 'fd-booking', name: 'Booking refused for large parties',
    summary: 'Bookings for parties of 7 to 8 are refused, below the real limit of 8.' },

  // Friction Detector
  { id: 'fr-info', tripwireId: 'friction-detector', parentId: null, name: 'Missing park information' },
  { id: 'fr-olympic', tripwireId: 'friction-detector', parentId: 'fr-info', name: 'Trail details missing for Olympic',
    summary: 'Visitor asks for Olympic trail lengths; the assistant gives vague answers after the trail lookup fails.' },
  { id: 'fr-amenities', tripwireId: 'friction-detector', parentId: 'fr-info', name: 'Campground amenities unknown',
    summary: 'Visitor asks which campgrounds have showers; the tools have no amenity data.' },
  { id: 'fr-booking', tripwireId: 'friction-detector', parentId: null, name: 'Booking problems' },
  { id: 'fr-soldout', tripwireId: 'friction-detector', parentId: 'fr-booking', name: 'Sold-out campsite dates',
    summary: 'Visitor is unhappy that the requested dates are sold out; the assistant behaves correctly.' },
  { id: 'fr-party', tripwireId: 'friction-detector', parentId: 'fr-booking', name: 'Booking refused for large parties',
    summary: 'Visitor with a party of 7 or 8 is told the limit is 6 and has to split the group.' },

  // Intent Classifier (fires on every trace)
  { id: 'ic-plan', tripwireId: 'intent-classifier', parentId: null, name: 'Planning a visit' },
  { id: 'ic-trails', tripwireId: 'intent-classifier', parentId: 'ic-plan', name: 'Trail recommendations', summary: 'Visitor wants a trail that fits their group.' },
  { id: 'ic-info', tripwireId: 'intent-classifier', parentId: 'ic-plan', name: 'Park information', summary: 'Visitor asks about hours, fees, conditions or amenities.' },
  { id: 'ic-book', tripwireId: 'intent-classifier', parentId: null, name: 'Booking' },
  { id: 'ic-campsite', tripwireId: 'intent-classifier', parentId: 'ic-book', name: 'Book a campsite', summary: 'Visitor wants to reserve a campsite.' },
  { id: 'ic-change', tripwireId: 'intent-classifier', parentId: 'ic-book', name: 'Change a booking', summary: 'Visitor wants to fix or change an existing booking.' },

  // Task Evaluator (fires on every trace)
  { id: 'te-done', tripwireId: 'task-evaluator', parentId: null, name: 'Task completed' },
  { id: 'te-done-book', tripwireId: 'task-evaluator', parentId: 'te-done', name: 'Booking completed', summary: 'A campsite was booked as asked.' },
  { id: 'te-done-info', tripwireId: 'task-evaluator', parentId: 'te-done', name: 'Question answered', summary: 'The visitor got the information they asked for.' },
  { id: 'te-not', tripwireId: 'task-evaluator', parentId: null, name: 'Task not completed' },
  { id: 'te-not-trail', tripwireId: 'task-evaluator', parentId: 'te-not', name: 'Trail question unanswered', summary: 'The visitor did not get the trail details they asked for.' },
  { id: 'te-not-book', tripwireId: 'task-evaluator', parentId: 'te-not', name: 'Booking not made', summary: 'The visitor left without the booking they wanted.' },

  // Made-up park facts (custom, from Oct 31)
  { id: 'mf-invented', tripwireId: 'made-up-park-facts', parentId: null, name: 'Invented park details' },
  { id: 'mf-trails', tripwireId: 'made-up-park-facts', parentId: 'mf-invented', name: 'Invented trail lengths at Olympic',
    summary: 'The assistant states a trail length for Olympic trails when the tool returned none.' },
  { id: 'mf-amenities', tripwireId: 'made-up-park-facts', parentId: 'mf-invented', name: 'Invented campground amenities',
    summary: 'The assistant says a campground has showers or hookups; the tool output does not say so.' },
];

// ---------------------------------------------------------------- event recipes
// Per leaf cluster: events per day (Oct 29 .. Nov 4), severities to rotate through,
// and example visitor messages + replies.

const RECIPES = {
  'fd-olympic': { perDay: [6, 7, 1, 0, 0, 0, 0], severity: ['critical', 'warning'],
    payload: { failure: 'Trail lookup raised an error for an Olympic trail', source: 'tool' },
    examples: [
      ['How long is the Hurricane Hill trail?', "I'm having trouble getting trail details right now. Please check the park website."],
      ['What are the easy hikes at Olympic?', "Sorry, I couldn't load the trail information for Olympic."],
    ] },
  'fd-party': { perDay: [1, 1, 2, 1, 1, 1, 0], severity: ['warning'],
    payload: { failure: 'Booking refused for a party of 7', source: 'tool' },
    examples: [
      ['Book a site for 7 people on Nov 12.', 'Sites hold up to 6 people. Would you like to book two sites?'],
    ] },
  'fr-olympic': { perDay: [5, 6, 1, 0, 0, 0, 0], severity: ['warning', 'critical', 'warning'],
    payload: { friction: 'Cannot get Olympic trail lengths', user_signal: 'asked three times' },
    examples: [
      ['I asked three times how long Hurricane Hill is. Can you just tell me?', "I'm sorry, I can't retrieve that trail's details right now."],
      ['Why can\'t you tell me anything about the trails?', 'The trail service is not returning details for Olympic at the moment.'],
      ['This is the third time. Just the length of the Lake Crescent trail, please.', "I'm unable to access that information."],
    ] },
  'fr-amenities': { perDay: [0, 1, 0, 1, 0, 1, 0], severity: ['info'],
    payload: { friction: 'Wants to know which campgrounds have showers', user_signal: 'asked again' },
    examples: [
      ['Which campgrounds have showers? I asked already.', "I don't have amenity details for the campgrounds."],
    ] },
  'fr-soldout': { perDay: [2, 1, 2, 2, 1, 2, 1], severity: ['info'],
    payload: { friction: 'Requested dates are sold out', user_signal: 'seriously, nothing at all' },
    examples: [
      ['Seriously, nothing at all that weekend?', 'All sites at Kalaloch are booked Nov 14 to 16. Mora has sites open.'],
      ['Ugh. Any other dates then?', 'Nov 21 to 23 has availability at Kalaloch.'],
    ] },
  'fr-party': { perDay: [1, 1, 1, 1, 1, 0, 1], severity: ['warning', 'info'],
    payload: { friction: 'Party of 7 told to split into two sites', user_signal: 'fine, I guess' },
    examples: [
      ['Fine, I guess we will split into two sites.', 'Booked sites 14 and 15 for Nov 12.'],
    ] },
  'mf-trails': { perDay: [0, 0, 2, 4, 3, 0, 0], severity: ['critical'],
    payload: { claim: 'Hurricane Hill is an easy 3-mile loop', evidence: 'Tool returned length_mi: null' },
    examples: [
      ['How long is Hurricane Hill?', 'Hurricane Hill is an easy 3-mile loop with great views.'],
      ['Is the Marymere Falls trail long?', "It's about 2.5 miles round trip and mostly flat."],
    ] },
  'mf-amenities': { perDay: [0, 0, 0, 1, 0, 1, 0], severity: ['warning'],
    payload: { claim: 'Kalaloch campground has hot showers', evidence: 'Tool output lists no amenities' },
    examples: [
      ['Does Kalaloch have showers?', 'Yes, Kalaloch has hot showers near the main loop.'],
    ] },
};

// Tripwires that produce an event for every trace they read (like Laminar's
// Intent Classifier and Task Evaluator). Traces are split across these clusters.
const EVERY_TRACE = {
  'intent-classifier': { split: [['ic-trails', 0.3], ['ic-info', 0.25], ['ic-campsite', 0.35], ['ic-change', 0.1]],
    payload: (c) => ({ intent: clusters.find((x) => x.id === c).name }) },
  'task-evaluator': { split: [['te-done-book', 0.35], ['te-done-info', 0.35], ['te-not-trail', 0.15], ['te-not-book', 0.15]],
    payload: (c) => ({ task: clusters.find((x) => x.id === c).name, outcome: c.startsWith('te-not') ? 'not completed' : 'completed' }) },
};

// ---------------------------------------------------------------- generation (deterministic)
// Everything below is computed once for the whole week. makeStoryData(asOf) then filters it.

let seed = 42;
const rand = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
const hex = (n) => Array.from({ length: n }, () => Math.floor(rand() * 16).toString(16)).join('');
const pad = (n) => String(n).padStart(2, '0');

// Traces: one per assistant turn, spread through each day (8am to 8pm; today stops before NOW).
export const traces = [];
TRACES_PER_DAY.forEach((count, d) => {
  const span = d === DAYS.length - 1 ? 80 : 12 * 60;
  for (let i = 0; i < count; i += 1) {
    const minutes = 8 * 60 + Math.floor(((i + 0.5) / count) * span);
    traces.push({
      id: hex(32), conversationId: `convo-${hex(8)}`, dayIndex: d,
      time: `${DAYS[d]}T${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}:00`,
      appVersion: APP_VERSION_BY_DAY[d],
    });
  }
});
const tracesOnDay = (d) => traces.filter((t) => t.dayIndex === d);

const ALL_EVENTS = [];
for (const [clusterId, r] of Object.entries(RECIPES)) {
  const cluster = clusters.find((c) => c.id === clusterId);
  let k = 0;
  r.perDay.forEach((count, d) => {
    const dayTraces = tracesOnDay(d);
    for (let i = 0; i < count; i += 1, k += 1) {
      // Spread this cluster's events over the day's traces.
      const trace = dayTraces[Math.floor(((i + 0.5) / count) * dayTraces.length)];
      const [visitor, reply] = r.examples[k % r.examples.length];
      ALL_EVENTS.push({
        id: `ev-${clusterId}-${k}`, tripwireId: cluster.tripwireId, clusterId,
        traceId: trace.id, conversationId: trace.conversationId, time: trace.time, appVersion: trace.appVersion,
        severity: r.severity[k % r.severity.length], payload: r.payload, excerpt: { visitor, reply },
      });
    }
  });
}
for (const [tripwireId, spec] of Object.entries(EVERY_TRACE)) {
  traces.forEach((trace, i) => {
    let x = rand(); let clusterId = spec.split[spec.split.length - 1][0];
    for (const [c, share] of spec.split) { if (x < share) { clusterId = c; break; } x -= share; }
    ALL_EVENTS.push({
      id: `ev-${tripwireId}-${i}`, tripwireId, clusterId,
      traceId: trace.id, conversationId: trace.conversationId, time: trace.time, appVersion: trace.appVersion,
      severity: clusterId.startsWith('te-not') ? 'warning' : 'info',
      payload: spec.payload(clusterId), excerpt: { visitor: '(see trace)', reply: '(see trace)' },
    });
  });
}
ALL_EVENTS.sort((a, b) => (a.time < b.time ? 1 : -1)); // newest first

// Notifications, following the alert rules (like Laminar):
//   new cluster: when a leaf cluster gets its first event;
//   new critical event: the first critical event in each cluster ("skip similar events").
const ALL_NOTIFICATIONS = (() => {
  const out = [];
  const byTime = [...ALL_EVENTS].sort((a, b) => (a.time < b.time ? -1 : 1));
  const seenCluster = new Set(); const seenCritical = new Set();
  for (const e of byTime) {
    const t = tripwires.find((x) => x.id === e.tripwireId);
    const c = clusters.find((x) => x.id === e.clusterId);
    if (!seenCluster.has(c.id)) {
      seenCluster.add(c.id);
      if (t.alerts.newCluster) {
        out.push({ id: `n-cluster-${c.id}`, time: e.time, type: 'new-cluster', tripwireId: t.id, clusterId: c.id,
          eventId: e.id, text: `New cluster in ${t.name}: ${c.name}` });
      }
    }
    if (e.severity === 'critical' && !seenCritical.has(c.id)) {
      seenCritical.add(c.id);
      if (t.alerts.newCriticalEvent) {
        out.push({ id: `n-critical-${e.id}`, time: e.time, type: 'critical-event', tripwireId: t.id, clusterId: c.id,
          eventId: e.id, text: `Critical event in ${t.name}: ${c.name}` });
      }
    }
  }
  return out.sort((a, b) => (a.time < b.time ? 1 : -1)); // newest first
})();

// ---------------------------------------------------------------- the story at a moment

const hoursBetween = (a, b) => (new Date(b) - new Date(a)) / 3_600_000;

// Everything a page needs, as it looked at `asOf` (an ISO time). Pages get this from useStoryData().
export function makeStoryData(asOf = NOW) {
  const asOfDate = asOf.slice(0, 10);
  const lastDayIndex = DAYS.filter((d) => d <= asOfDate).length - 1;

  const events = ALL_EVENTS.filter((e) => e.time <= asOf);
  const liveTripwires = tripwires.filter((t) => t.createdAt <= asOfDate);
  const liveLeafIds = new Set(events.map((e) => e.clusterId));
  const liveClusters = clusters.filter((c) => (c.parentId
    ? liveLeafIds.has(c.id)
    : clusters.some((child) => child.parentId === c.id && liveLeafIds.has(child.id))));
  const notifications = ALL_NOTIFICATIONS.filter((n) => n.time <= asOf)
    .map((n) => ({ ...n, read: hoursBetween(n.time, asOf) > UNREAD_FOR_HOURS }));

  const getTripwire = (id) => liveTripwires.find((t) => t.id === id);
  const getCluster = (id) => liveClusters.find((c) => c.id === id);
  const getEvent = (id) => events.find((e) => e.id === id);
  const eventsFor = (tripwireId) => events.filter((e) => e.tripwireId === tripwireId);
  const subClusters = (clusterId) => liveClusters.filter((c) => c.parentId === clusterId);
  const eventsInCluster = (clusterId) => {
    const leafIds = subClusters(clusterId).map((c) => c.id);
    const ids = leafIds.length ? leafIds : [clusterId];
    return events.filter((e) => ids.includes(e.clusterId));
  };
  const topClusters = (tripwireId) => liveClusters.filter((c) => c.tripwireId === tripwireId && !c.parentId);
  const leafClusters = (tripwireId) => liveClusters.filter((c) => c.tripwireId === tripwireId && c.parentId);

  // Events per day, always all 7 days so the x-axis doesn't jump; days after asOf are null (no line).
  const eventsPerDay = (tripwireId, clusterId) => DAYS.map((day, d) => ({
    day: DAY_LABELS[d],
    events: d > lastDayIndex ? null
      : (clusterId ? eventsInCluster(clusterId) : eventsFor(tripwireId)).filter((e) => e.time.startsWith(day)).length,
  }));

  // Traces the tripwire read (its runs): every trace since it was created, up to asOf.
  const runsFor = (tripwireId) => {
    const t = getTripwire(tripwireId);
    return traces.filter((tr) => tr.time <= asOf && tr.time.slice(0, 10) >= t.createdAt).length;
  };

  // One row per tripwire, for the Tripwire list (same columns as Laminar's Signals list).
  const tripwireSummary = (tripwireId) => {
    const t = getTripwire(tripwireId);
    const own = eventsFor(tripwireId);
    return {
      ...t,
      events: own.length,
      clusters: leafClusters(tripwireId).length,
      runs: runsFor(tripwireId),
      activity: eventsPerDay(tripwireId).filter((d) => d.events !== null).map((d) => d.events),
      lastEventAt: own[0]?.time ?? null,
    };
  };

  return {
    asOf, days: DAY_LABELS,
    tripwireTemplates, sampleTraces: tripwireSamples.filter((sample) => sample.time <= asOf),
    tripwires: liveTripwires, clusters: liveClusters, tripwireEvents: events, notifications,
    getTripwire, getCluster, getEvent, eventsFor, eventsInCluster, topClusters, subClusters, leafClusters,
    eventsPerDay, runsFor, tripwireSummary,
    unreadCount: () => notifications.filter((n) => !n.read).length,
  };
}

export const laminarTraceUrl = (traceId) => `${LAMINAR_PROJECT_URL}/traces/${traceId}`;
