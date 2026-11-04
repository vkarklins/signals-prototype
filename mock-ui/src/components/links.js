// Links between screens. Use these instead of writing URLs by hand, so every page links the same way.
//
// Tripwire detail reads two optional query parameters:
//   ?cluster=<clusterId>  the cluster selected in the cluster tree (filters the events table)
//   ?event=<eventId>      the event to highlight in the events table
// Read them on the detail page with: const [params] = useSearchParams(); params.get('cluster')

export const homeUrl = () => '/';
export const tripwireListUrl = () => '/tripwires';
export const newTripwireUrl = () => '/tripwires/new';
export const notificationsUrl = () => '/notifications';

export function tripwireUrl(tripwireId, { clusterId, eventId } = {}) {
  const params = new URLSearchParams();
  if (clusterId) params.set('cluster', clusterId);
  if (eventId) params.set('event', eventId);
  const query = params.toString();
  return `/tripwires/${tripwireId}${query ? `?${query}` : ''}`;
}

// Where a notification leads: the tripwire, with its cluster selected and its event highlighted.
export const notificationUrl = (n) => tripwireUrl(n.tripwireId, { clusterId: n.clusterId, eventId: n.eventId });
