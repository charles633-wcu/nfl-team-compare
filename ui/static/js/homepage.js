document.addEventListener("DOMContentLoaded", () => {
  const revealNodes = document.querySelectorAll(".reveal-on-scroll");
  if (!revealNodes.length) {
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) {
          return;
        }
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    {
      threshold: 0.18,
      rootMargin: "0px 0px -8% 0px",
    },
  );

  revealNodes.forEach((node) => observer.observe(node));
});
