import { Button } from '@mantine/core';
import { Link } from 'react-router-dom';
import Placeholder from '../components/Placeholder';
import { newTripwireUrl } from '../components/links';

export default function TripwireList() {
  return (
    <Placeholder title="Signals" actions={<Button component={Link} to={newTripwireUrl()}>New signal</Button>} shows={[
      "Table modeled on Laminar's Signals list: Status, Name, Events, Clusters, Activity, Last event, Runs, Created",
      'Search by name, time range (default 7 days)',
      'New signal button',
      'Click a row to open the signal',
    ]} />
  );
}
