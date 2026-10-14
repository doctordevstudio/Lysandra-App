(function () {
  var b = document.getElementById('burger'), d = document.getElementById('drawer'), s = document.getElementById('scrim');
  function set(open) {
    d.classList.toggle('open', open); s.classList.toggle('open', open);
    b.setAttribute('aria-expanded', open ? 'true' : 'false'); d.setAttribute('aria-hidden', open ? 'false' : 'true');
    document.body.classList.toggle('lock', open);
  }
  b.addEventListener('click', function () { set(!d.classList.contains('open')); });
  s.addEventListener('click', function () { set(false); });
  d.addEventListener('click', function (e) { if (e.target.tagName === 'A') set(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') set(false); });
  var els = document.querySelectorAll('.card,.plan,.steps li,.faq details');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (es) { es.forEach(function (x) { if (x.isIntersecting) { x.target.classList.add('in'); io.unobserve(x.target); } }); }, { threshold: .12 });
    els.forEach(function (e) { e.classList.add('reveal'); io.observe(e); });
  }
})();
