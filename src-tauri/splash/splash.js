// The start-up page. The app replaces it with the calculator as soon as the engine is listening; if the engine cannot start,
// the app calls window.scicalFailed(message) to say why.
window.scicalFailed = function (message) {
  document.body.classList.add('failed');
  document.getElementById('msg').textContent = String(message || 'SciCal could not start.');
};
setTimeout(function () {
  var msg = document.getElementById('msg');
  if (msg && !document.body.classList.contains('failed')) msg.textContent = 'Still starting… the first start can take a little longer.';
}, 8000);
