#!/bin/sh
# measure.sh RUN...  : the usersession counters from a run's console.log
cd /data/hackios-qemu/research/ios26-apps-r1/runs
for r in "$@"; do f=$r/console.log; [ -f $f ] || continue
 printf '%s: persona_alloc_uid501=%s persona_alloc_total=%s INVALID_PERSONA=%s lsd_abort=%s no_personas=%s session_notfound=%s swapfail=%s us_sel=%s us_refused=%s type6_err=%s registered=%s\n' "$r" \
  "$(grep -a 'hk_persona: .* alloc .* uid 501 .*-> 0' $f | wc -l)" "$(grep -a 'hk_persona: .* alloc .*-> 0' $f | wc -l)" \
  "$(grep -ac 'INVALID_PERSONA' $f)" "$(grep -ac 'userabort: lsd' $f)" "$(grep -ac 'no personas found' $f)" \
  "$(grep -ac 'could not find the requested session' $f)" "$(grep -aci 'atomically swap\|Failed to save persona manifest' $f)" \
  "$(grep -aE 'SWEET AKS: [A-Za-z_]+ sel (2|3|6|65|96|97|98|117) ' $f | wc -l)" "$(grep -ac 'user session sel .* refused' $f)" \
  "$(grep -ac 'Unable to find persona with type' $f)" "$(grep -aic 'registerApplication\|Registered app\|registered bundle' $f)"
done
