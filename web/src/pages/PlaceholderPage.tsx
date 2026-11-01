export default function PlaceholderPage(props: { title: string; note: string }) {
  return (
    <section aria-label={props.title}>
      <p class="hero-kicker">Staged for a later phase</p>
      <h2 class="hero-headline">{props.title}</h2>
      <p class="hero-dek">{props.note}</p>
      <div class="alert alert-warn" role="status">
        <h3>Pending section</h3>
        <p>This route renders a deliberate placeholder. No mock curve is shown here.</p>
      </div>
    </section>
  );
}
