import Placeholder from '../components/Placeholder';

export default function Home() {
  return (
    <Placeholder title="Home" shows={[
      'Signals that are spiking',
      'Newly formed clusters',
      'Recent critical signal events',
      'Unread notifications',
      'Each item links to its signal or cluster',
    ]} />
  );
}
