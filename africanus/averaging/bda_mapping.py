# -*- coding: utf-8 -*-

import numpy as np
import numba

from astropy.time import Time
from astropy.coordinates import SkyCoord, EarthLocation

from africanus.constants import c as lightspeed
from africanus.util.numba import generated_jit, njit
from africanus.averaging.support import unique_time, unique_baselines

class RowMapperError(Exception):
    pass

    # if isinstance(lm_max, np.ndarray):
    #     if not lm_max.shape == (2,):
    #         raise ValueError("lm_max must have shape 2 if an ndarray")

    #     l, m = lm_max
    # elif isinstance(lm_max, (tuple, list)):
    #     if not len(lm_max) == 2:
    #         raise ValueError("lm_max must have length 2 if tuple/list")

    #     l, m = lm_max
    # elif isinstance(lm_max, (int, float)):
    #     l = m = np.sqrt(lm_max / 2)
    # else:
    #     raise TypeError("lm_max must a single float, or a "
    #                     "tuple/list/ndarray of 2 elements")




def duv_dt(utime, ubl, ants, chan_freq, phase_dir):
    # Unique ant1 and ant2
    uant1 = ubl[:, 0]
    uant2 = ubl[:, 1]

    # Dimensions
    ntime = utime.shape[0]
    nbl = ubl.shape[0]
    nchan = chan_freq.shape[0]

    ast_centre = EarthLocation.from_geocentric(ants[:, 0].mean(),
                                               ants[:, 1].mean(),
                                               ants[:, 2].mean(),
                                               unit="m")
    lon, lat, alt = ast_centre.to_geodetic()
    ast_time = Time(utime / 86400.00, format='mjd', scale='ut1')
    ast_phase_dir = SkyCoord(ra=phase_dir[0], dec=phase_dir[1], unit='rad')

    # Get hour angle and dec, convert to radians
    ha = ast_time.sidereal_time("apparent", lon) - ast_phase_dir.ra
    ha = ha.to('rad').value
    dec = ast_phase_dir.dec.to('rad').value

    # Numeric derivative of the hour angle with respect to time
    # http://kitchingroup.cheme.cmu.edu/blog/2013/02/27/Numeric-derivatives-by-differences/
    𝞓ha𝞓t = np.empty_like(ha)
    t = utime
    𝞓ha𝞓t[0] = (ha[0] - ha[1]) / (t[0] - t[1])
    𝞓ha𝞓t[1:-1] = (ha[2:] - ha[:-2]) / (t[2:] - t[:-2])
    𝞓ha𝞓t[-1] = (ha[-1] - ha[-2]) / (t[-1] - t[-2])

    # Baseline antenna position difference
    Lx = (ants[uant1, 0] - ants[uant2, 0])[:, None, None]
    Ly = (ants[uant1, 1] - ants[uant2, 1])[:, None, None]
    Lz = (ants[uant2, 2] - ants[uant2, 2])[:, None, None]

    # Prepare the result array
    dtype = np.result_type(Lx, ha, chan_freq)
    𝞓uv𝞓t = np.empty((nbl, ntime, nchan, 2), dtype)

    # Synthesis and Imaging 18-33 and 18-34
    spatial_freq = chan_freq[None, None, :] / lightspeed
    ha = ha[None, :, None]
    𝞓uv𝞓t[..., 0] = spatial_freq * (Lx*np.cos(ha) - Ly*np.sin(ha))
    𝞓uv𝞓t[..., 1] = spatial_freq * (Lx*np.sin(dec)*np.sin(ha) +
                                     Ly*np.sin(dec)*np.cos(ha))
    𝞓uv𝞓t *= 𝞓ha𝞓t[None, :, None, None]
    return 𝞓uv𝞓t

def row_mapper(time, uvw, ants, phase_dir, ref_freq, lm_max):
    """
    Parameters
    ----------

    Returns
    -------
    """
    time = np.unique(time)  # Remove duplicate times

    if isinstance(lm_max, np.ndarray):
        if not lm_max.shape == (2,):
            raise ValueError("lm_max must have shape 2 if an ndarray")

        l, m = lm_max
    elif isinstance(lm_max, (tuple, list)):
        if not len(lm_max) == 2:
            raise ValueError("lm_max must have length 2 if tuple/list")

        l, m = lm_max
    elif isinstance(lm_max, (int, float)):
        l = m = np.sqrt(lm_max / 2)
    else:
        raise TypeError("lm_max must a single float, or a "
                        "tuple/list/ndarray of 2 elements")

    ant1, ant2 = (a.astype(np.int32) for a in np.triu_indices(ants.shape[0], 1))
    ntime = time.shape[0]
    nbl = ant1.shape[0]

    ast_centre = EarthLocation.from_geocentric(ants[:, 0].mean(),
                                               ants[:, 1].mean(),
                                               ants[:, 2].mean(),
                                               unit="m")
    lon, lat, alt = ast_centre.to_geodetic()
    ast_time = Time(time / 86400.00, format='mjd', scale='ut1')
    ast_phase_dir = SkyCoord(ra=phase_dir[0], dec=phase_dir[1], unit='rad')

    # Get hour angle and dec, convert to radians
    ha = ast_time.sidereal_time("apparent", lon) - ast_phase_dir.ra
    ha = ha.to('rad').value
    dec = ast_phase_dir.dec.to('rad').value

    # Numeric derivate of the hour angle with respect to time
    # http://kitchingroup.cheme.cmu.edu/blog/2013/02/27/Numeric-derivatives-by-differences/
    𝞓ha𝞓t = np.empty_like(ha)
    t = time
    𝞓ha𝞓t[0] = (ha[0] - ha[1]) / (t[0] - t[1])
    𝞓ha𝞓t[1:-1] = (ha[2:] - ha[:-2]) / (t[2:] - t[:-2])
    𝞓ha𝞓t[-1] = (ha[-1] - ha[-2]) / (t[-1] - t[-2])

    # Baseline antenna position difference
    Lx = (ants[ant1, 0] - ants[ant2, 0])[:, None]
    Ly = (ants[ant1, 1] - ants[ant2, 1])[:, None]
    Lz = (ants[ant2, 2] - ants[ant2, 2])[:, None]

    # Synthesis and Imaging 18-33 and 18-34
    spatial_freq = ref_freq / lightspeed
    ha = ha[None, :]
    𝞓ha𝞓t = 𝞓ha𝞓t[None, :]
    𝞓u𝞓t = spatial_freq * (Lx*np.cos(ha) - Ly*np.sin(ha))
    𝞓v𝞓t = spatial_freq * (Lx*np.sin(dec)*np.sin(ha) + Ly*np.sin(dec)*np.cos(ha))
    𝞓u𝞓t *= 𝞓ha𝞓t
    𝞓v𝞓t *= 𝞓ha𝞓t

    # (bl, time)
    assert 𝞓u𝞓t.shape == (Lx.shape[0], time.shape[0])

    # 𝞓u𝞓t = 𝞓u𝞓t.ravel()
    # 𝞓v𝞓t = 𝞓v𝞓t.ravel()

    # Synthesis and Imaging 18-31. Reduction in Amplitude
    𝞓𝞍𝞓t = 𝞓u𝞓t*l + 𝞓v𝞓t*m

    v = 𝞓𝞍𝞓t* np.pi
    v[v == 0] = 1.0
    R = np.sin(v) / v

    # 𝞓𝞍𝞓t = 2 * np.pi * 𝞓𝞍𝞓t[:, :, None] * chan_freq[None, None, :] / lightspeed

    return R


@njit(nogil=True, cache=True)
def _impl(time, interval, ant1, ant2, uvw, ref_freq,
          chan_freq, chan_width, lm_max=1, decorrelation=0.98):
    # 𝞓 𝝿 𝞇 𝞍 𝝼

    if decorrelation < 0.0 or decorrelation > 1.0:
        raise ValueError("0.0 <= decorrelation <= 1.0 must hold")

    l = m = np.sqrt(0.5 * lm_max)
    n_term = 1.0 - l**2 - m**2
    n_max = np.sqrt(n_term) - 1.0 if n_term >= 0.0 else -1.0

    ubl, _, bl_inv, _ = unique_baselines(ant1, ant2)
    utime, _, time_inv, _ = unique_time(time)

    nrow = time.shape[0]
    ntime = utime.shape[0]
    nbl = ubl.shape[0]

    sentinel = np.finfo(time.dtype).max

    shape = (nbl, ntime)
    row_lookup = np.full(shape, -1, dtype=np.int32)

    for r in range(nrow):
        t = time_inv[r]
        bl = bl_inv[r]

        if row_lookup[bl, t] != -1:
            raise ValueError("Duplicate (TIME, ANTENNA1, ANTENNA2)")

        row_lookup[bl, t] = r

    for bl in range(nbl):
        tbin = numba.int32(0)
        bin_count = numba.int32(0)
        bin_flag_count = numba.int32(0)
        bin_time_low = time.dtype.type(0)
        bin_u_low = uvw.dtype.type(0)
        bin_v_low = uvw.dtype.type(0)
        bin_w_low = uvw.dtype.type(0)
        bin_sinc_𝞓𝞇 = uvw.dtype.type(0)

        for t in range(ntime):
            r = row_lookup[bl ,t]

            if r == -1:
                continue

            half_int = interval[r] * 0.5

            # We're starting a new bin anyway,
            # just set the lower bin value
            if bin_count == 0:
                bin_time_low = time[r] - half_int
                bin_u_low = uvw[r, 0]
                bin_v_low = uvw[r, 1]
                bin_w_low = uvw[r, 2]
                bin_sinc_𝞓𝞇 = 0
            else:
                # Evaluate the degree of decorrelation
                # the sample would add to the bin
                dt = time[r] + half_int - bin_time_low
                du = uvw[r, 0] - bin_u_low
                dv = uvw[r, 1] - bin_v_low
                dw = uvw[r, 2] - bin_w_low

                du_dt = l * du / dt
                dv_dt = m * dv / dt

                # Derive phase difference in time
                # from Equation (33) in Atemkeng
                𝞓𝞇 = np.pi * (du_dt + dv_dt)
                sinc_𝞓𝞇 = 1.0 if 𝞓𝞇 == 0.0 else np.sin(𝞓𝞇) / 𝞓𝞇

                # We're not decorrelated at this point,
                # but keep a record of the sinc_𝞓𝞇
                if sinc_𝞓𝞇 > decorrelation:
                    bin_sinc_𝞓𝞇 = sinc_𝞓𝞇
                else:
                    # Contents of the bin exceed decorrelation tolerance
                    # Finalise it and start a new one

                    # Handle special case of bin containing a single sample.
                    # Change in baseline speed 𝞓𝞇 == 0
                    if bin_count == 1:
                        du = bin_u_low
                        dv = bin_v_low
                        dw = bin_w_low
                        bin_sinc_𝞓𝞇 = sinc_𝞓𝞇 = 1.0
                        sinc_𝞓𝞍 = decorrelation
                    else:
                        # Phase at the centre of the bin and reference frequency
                        phase = 1.0

                        # Given
                        #   (1) acceptable decorrelation
                        #   (2) change in baseline speed
                        # derive the frequency phase difference
                        # from Equation (35) in Atemkeng
                        sinc_𝞓𝞍 = decorrelation / bin_sinc_𝞓𝞇

                        # Use Newton Raphson to find frequency phase difference 𝞍
                        # https://stackoverflow.com/a/30205309/1611416
                        eps = 1.0
                        𝞓𝞍 = np.pi  # Starting guess. sinc Taylor series maybe appropriate

                        while np.abs(eps) > 1e-12:
                            # Try negative range if we hit zero
                            if 𝞓𝞍 == 0.0:
                                𝞓𝞍 = -np.pi

                            # compute sinc of 𝞓𝞍 on this iteration
                            it_sinc_𝞓𝞍 = np.sin(𝞓𝞍) / 𝞓𝞍

                            # For very small 𝞓𝞍, sinc(𝞓𝞍) == 𝞓𝞍 can hold
                            # We've found a solution when it does
                            if it_sinc_𝞓𝞍 == 1.0:
                                break

                            # derivative of sinc of 𝞓𝞍 on this iteration
                            dit_sinc_𝞓𝞍 = (np.cos(𝞓𝞍) - it_sinc_𝞓𝞍) / 𝞓𝞍

                            # Difference at this iteration
                            eps = it_sinc_𝞓𝞍 - sinc_𝞓𝞍
                            # Newton Raphson update
                            𝞓𝞍 = 𝞓𝞍 - eps / dit_sinc_𝞓𝞍

                    # Derive fractional bandwidth 𝞓𝝼/𝝼
                    # from Equation (44) in Atemkeng
                    max_abs_dist = np.sqrt(np.abs(du)*np.abs(l) + 
                                           np.abs(dv)*np.abs(m) +
                                           np.abs(dw)*np.abs(n_max))

                    if max_abs_dist == 0.0:
                        raise ValueError("max_abs_dist == 0.0")

                    fractional_bandwidth = 𝞓𝞍 / max_abs_dist

                    # Derive max_𝞓𝝼, the maximum change in bandwidth
                    # before decorrelation occurs in frequency
                    #
                    # fractional bandwidth is defined by
                    # https://en.wikipedia.org/wiki/Bandwidth_(signal_processing)
                    # for wideband antennas as:
                    #   (1) 𝞓𝝼/𝝼 = fb = (fh - fl) / (fh + fl)
                    # where fh and fl are the high and low frequencies
                    # of the band.
                    # We set fh = ref_freq + 𝞓𝝼/2, fl = ref_freq - 𝞓𝝼/2
                    # Then, simplifying (1), 𝞓𝝼 = 2 * ref_freq * fb
                    max_𝞓𝝼 = 2 * ref_freq * fractional_bandwidth

                    bin_freq_low = chan_freq[0] - chan_width[0] / 2
                    bin_chan_low = 0
                    bin_𝞓𝝼 = 0

                    chan_bins = 0

                    for c in range(1, chan_freq.shape[0]):
                        # Bin bandwidth
                        𝞓𝝼 = chan_freq[c] + chan_width[c] / 2 - bin_freq_low

                        # Exceeds, start new channel bin
                        if 𝞓𝝼 > max_𝞓𝝼:
                            bin_chan_low = c
                            bin_freq_low = chan_freq[c] - chan_width[c] / 2
                            chan_bins += 1

                    chan_bins += 1            

                    print(bl, bin_count, tbin, "max_𝞓𝝼", max_𝞓𝝼, "dist", max_abs_dist, chan_bins)

                    tbin += 1
                    bin_count = 0
                    bin_time_low = time[r] - half_int
                    bin_u_low = uvw[r, 0]
                    bin_v_low = uvw[r, 1]
                    bin_w_low = uvw[r, 2]
                    bin_flag_count = 0


            bin_count += 1

def atemkeng_mapper(time, interval, ant1, ant2, uvw,
                    ref_freq, chan_freq, chan_width):
    _impl(time, interval, ant1, ant2, uvw,
          ref_freq, chan_freq, chan_width)