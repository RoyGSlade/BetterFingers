// Vite-resolved assets for the Signal Engineer face shells.
// Kept apart from signalEngineerFace.mjs so that module stays importable from
// plain Node (tests, scripts/export-signal-engineer-svg.mjs), which cannot
// import PNGs. Regenerate the PNGs with tools/signal_engineer_parts.py.
import standardSpec from '../assets/signal-engineer/standard.parts.json';
import chassis from '../assets/signal-engineer/chassis.png';
import earLeft from '../assets/signal-engineer/earLeft.png';
import earRight from '../assets/signal-engineer/earRight.png';
import browLeft from '../assets/signal-engineer/browLeft.png';
import browRight from '../assets/signal-engineer/browRight.png';

import rustSpec from '../assets/signal-engineer/rustbucket.parts.json';
import rChassis from '../assets/signal-engineer/rustbucket/chassis.png';
import rEarLeft from '../assets/signal-engineer/rustbucket/earLeft.png';
import rEarRight from '../assets/signal-engineer/rustbucket/earRight.png';
import rBrowLeft from '../assets/signal-engineer/rustbucket/browLeft.png';
import rBrowRight from '../assets/signal-engineer/rustbucket/browRight.png';
import rBeardCenter from '../assets/signal-engineer/rustbucket/beardCenter.png';
import rMustache from '../assets/signal-engineer/rustbucket/mustache.png';
import rSideBeard from '../assets/signal-engineer/rustbucket/sideBeard.png';

import sweetSpec from '../assets/signal-engineer/sweetheart.parts.json';
import sChassis from '../assets/signal-engineer/sweetheart/chassis.png';
import sEarLeft from '../assets/signal-engineer/sweetheart/earLeft.png';
import sEarRight from '../assets/signal-engineer/sweetheart/earRight.png';
import sBrowLeft from '../assets/signal-engineer/sweetheart/browLeft.png';
import sBrowRight from '../assets/signal-engineer/sweetheart/browRight.png';
import sBow from '../assets/signal-engineer/sweetheart/bow.png';

/** Overlay appearance `face` value -> shell. */
export const FACE_SHELLS = Object.freeze({
  'signal-engineer': {
    spec: standardSpec,
    partUrls: { chassis, earLeft, earRight, browLeft, browRight },
  },
  sweetheart: {
    spec: sweetSpec,
    partUrls: { chassis: sChassis, earLeft: sEarLeft, earRight: sEarRight, browLeft: sBrowLeft, browRight: sBrowRight, bow: sBow },
  },
  rustbucket: {
    spec: rustSpec,
    partUrls: {
      chassis: rChassis, earLeft: rEarLeft, earRight: rEarRight, browLeft: rBrowLeft, browRight: rBrowRight,
      beardCenter: rBeardCenter, mustache: rMustache, sideBeard: rSideBeard,
    },
  },
});

export function faceAspect(spec) {
  return spec.viewBox[2] / spec.viewBox[3];
}
