import { LAMINAR_PROJECT_URL } from '../mock/data';

// Links between screens. Use these instead of writing URLs by hand, so every page links the same way.
//
// Tripwire detail reads these optional query parameters:
//   ?tab=events|runs|settings  which tab is open (default events)
//   ?cluster=<clusterId>       the selected cluster (filters the chart and the events table)
//   ?event=<eventId>           an event to open in the side panel
//   ?pastHours=168 or ?startDate=&endDate=   the time range (see timeRange.js)
// Read them on the detail page with: const [params] = useSearchParams(); params.get('cluster')

export const homeUrl = () => '/';
export const tripwireListUrl = () => '/signals';
export const newTripwireUrl = () => '/signals/new';
export const notificationsUrl = () => '/notifications';

export function tripwireUrl(tripwireId, { tab, clusterId, eventId } = {}) {
  const params = new URLSearchParams();
  if (tab && tab !== 'events') params.set('tab', tab);
  if (clusterId) params.set('cluster', clusterId);
  if (eventId) params.set('event', eventId);
  const query = params.toString();
  return `/signals/${tripwireId}${query ? `?${query}` : ''}`;
}

// Where a notification leads: the tripwire, with its cluster selected and its event highlighted.
export const notificationUrl = (n) => tripwireUrl(n.tripwireId, { clusterId: n.clusterId, eventId: n.eventId });

// A trace in Laminar (opens Laminar's trace view).
export const laminarTraceUrl = (traceId) => `${LAMINAR_PROJECT_URL}/traces/${traceId}`;
