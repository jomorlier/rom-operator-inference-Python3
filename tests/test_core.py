# test_core.py
"""Tests for rom_operator_inference._core.py."""

import pytest
import warnings
import itertools
import numpy as np
from scipy import linalg as la

import rom_operator_inference as roi


# Helper functions for testing ================================================
_MODEL_KEYS = roi._core._BaseROM._MODEL_KEYS
_MODEL_FORMS = [''.join(s) for k in range(1, len(_MODEL_KEYS)+1)
                           for s in itertools.combinations(_MODEL_KEYS, k)]


def _get_data(n=200, k=50, m=20):
    X = np.random.random((n,k))
    Xdot = np.zeros((n,k))
    U = np.ones((m,k))

    return X, Xdot, U

def _get_operators(n=200, m=20):
    c = np.random.random(n)
    A = np.eye(n)
    H = np.zeros((n,n**2))
    Hc = np.zeros((n,n*(n+1)//2))
    B = np.random.random((n,m)) if m else None
    return c, A, H, Hc, B

def _trainedmodel(continuous, modelform, Vr, m=20):
    if continuous:
        modelclass = roi._core._ContinuousROM
    else:
        modelclass = roi._core._DiscreteROM

    n,r = Vr.shape
    c, A, H, Hc, B = _get_operators(r, m)
    operators = {}
    if "A" in modelform:
        operators['A_'] = A
    if "H" in modelform:
        operators['Hc_'] = Hc
    if "c" in modelform:
        operators['c_'] = c
    if "B" in modelform:
        operators['B_'] = B

    return roi._core.trained_model_from_operators(modelclass, modelform,
                                                   Vr, **operators)


# Helper classes and functions ================================================
class TestAffineOperator:
    """Test _core.AffineOperator."""
    @staticmethod
    def _set_up_affine_attributes(n=5):
        fs = [np.sin, np.cos, np.exp]
        As = list(np.random.random((3,n,n)))
        return fs, As

    def test_init(self):
        """Test _core.AffineOperator.__init__()."""
        fs, As = self._set_up_affine_attributes()

        # Try with different number of functions and matrices.
        with pytest.raises(ValueError) as ex:
            roi._core.AffineOperator(fs, As[:-1])
        assert ex.value.args[0] == "expected 3 matrices, got 2"

        # Try with matrices of different shapes.
        with pytest.raises(ValueError) as ex:
            roi._core.AffineOperator(fs, As[:-1] + [np.random.random((4,4))])
        assert ex.value.args[0] == \
            "affine operator matrix shapes do not match ((4, 4) != (5, 5))"

        # Correct usage.
        affop = roi._core.AffineOperator(fs, As)
        affop = roi._core.AffineOperator(fs)
        affop.matrices = As

    def test_validate_coeffs(self):
        """Test _core.AffineOperator.validate_coeffs()."""
        fs, As = self._set_up_affine_attributes()

        # Try with non-callables.
        affop = roi._core.AffineOperator(As)
        with pytest.raises(ValueError) as ex:
            affop.validate_coeffs(10)
        assert ex.value.args[0] == \
            "coefficients of affine operator must be callable functions"

        # Try with vector-valued functions.
        f1 = lambda t: np.array([t, t**2])
        affop = roi._core.AffineOperator([f1, f1])
        with pytest.raises(ValueError) as ex:
            affop.validate_coeffs(10)
        assert ex.value.args[0] == \
            "coefficient functions of affine operator must return a scalar"

        # Correct usage.
        affop = roi._core.AffineOperator(fs, As)
        affop.validate_coeffs(0)

    def test_call(self):
        """Test _core.AffineOperator.__call__()."""
        fs, As = self._set_up_affine_attributes()

        # Try without matrices set.
        affop = roi._core.AffineOperator(fs)
        with pytest.raises(RuntimeError) as ex:
            affop(10)
        assert ex.value.args[0] == "constituent matrices not initialized!"

        # Correct usage.
        affop.matrices = As
        Ap = affop(10)
        assert Ap.shape == (5,5)
        assert np.allclose(Ap, np.sin(10)*As[0] + \
                               np.cos(10)*As[1] + np.exp(10)*As[2])


def testtrained_model_from_operators():
    """Test _core.trained_model_from_operators()."""
    n, m, r = 200, 20, 30
    Vr = np.random.random((n, r))
    c, A, H, Hc, B = _get_operators(n=n, m=m)

    # Try with bad modelclass argument.
    with pytest.raises(TypeError) as ex:
        roi._core.trained_model_from_operators(str, "cAH", Vr)
    assert ex.value.args[0] == "modelclass must be derived from _BaseROM"

    # Correct usage.
    roi._core.trained_model_from_operators(roi._core._ContinuousROM,
                                "cAH", Vr, A_=A, Hc_=Hc, c_=c)
    roi._core.trained_model_from_operators(roi._core._ContinuousROM,
                                "AB", Vr, A_=A, B_=B)


# Base classes ================================================================
class TestBaseROM:
    """Test _core._BaseROM."""
    def test_init(self):
        """Test _BaseROM.__init__()."""
        with pytest.raises(TypeError) as ex:
            roi._core._BaseROM()
        assert ex.value.args[0] == \
            "__init__() missing 1 required positional argument: 'modelform'"

        with pytest.raises(TypeError) as ex:
            roi._core._BaseROM("cAH", False)
        assert ex.value.args[0] == \
            "__init__() takes 2 positional arguments but 3 were given"

        model = roi._core._BaseROM("cA")
        assert hasattr(model, "modelform")
        assert hasattr(model, "_form")
        assert hasattr(model, "has_inputs")
        assert model.modelform == "cA"
        assert model.has_constant is True
        assert model.has_linear is True
        assert model.has_quadratic is False
        assert model.has_inputs is False

        model.modelform = "BHc"
        assert model.modelform == "cHB"
        assert model.has_constant is True
        assert model.has_linear is False
        assert model.has_quadratic is True
        assert model.has_inputs is True

    def test_check_modelform(self):
        """Test _BaseROM._check_modelform()."""
        Vr = np.random.random((200,5))
        m = 20

        # Try with invalid modelform.
        model = roi._core._BaseROM("bad_form")
        with pytest.raises(ValueError) as ex:
            model._check_modelform(trained=False)
        assert ex.value.args[0] == \
            "invalid modelform key 'b'; " \
            f"options are {', '.join(model._MODEL_KEYS)}"

        # Try with untrained model.
        model.modelform = "cAH"
        with pytest.raises(AttributeError) as ex:
            model._check_modelform(trained=True)
        assert ex.value.args[0] == \
            "attribute 'c_' missing; call fit() to train model"

        # Try with missing attributes.
        model = _trainedmodel(True, "cAHB", Vr, m)
        c_ = model.c_.copy()
        del model.c_
        with pytest.raises(AttributeError) as ex:
            model._check_modelform(trained=True)
        assert ex.value.args[0] == \
            "attribute 'c_' missing; call fit() to train model"
        model.c_ = c_

        B_ = model.B_.copy()
        del model.B_
        with pytest.raises(AttributeError) as ex:
            model._check_modelform(trained=True)
        assert ex.value.args[0] == \
            "attribute 'B_' missing; call fit() to train model"
        model.B_ = B_

        # Try with incorrectly set attributes.
        A_ = model.A_.copy()
        model.A_ = None
        with pytest.raises(AttributeError) as ex:
            model._check_modelform(trained=True)
        assert ex.value.args[0] == \
            "attribute 'A_' is None; call fit() to train model"

        model = _trainedmodel(True, "cAB", Vr, m)
        model.Hc_ = 1
        with pytest.raises(AttributeError) as ex:
            model._check_modelform(trained=True)
        assert ex.value.args[0] == \
            "attribute 'Hc_' should be None; call fit() to train model"
        model.Hc_ = None

        model.modelform = "cA"
        with pytest.raises(AttributeError) as ex:
            model._check_modelform(trained=True)
        assert ex.value.args[0] == \
            "attribute 'B_' should be None; call fit() to train model"

        model = _trainedmodel(False, "cAH", Vr, None)
        model.modelform = "cAHB"
        with pytest.raises(AttributeError) as ex:
            model._check_modelform(trained=True)
        assert ex.value.args[0] == \
            "attribute 'B_' is None; call fit() to train model"

    def test_check_inputargs(self):
        """Test _BaseROM._check_inputargs()."""

        # Try with has_inputs = True but without inputs.
        model = roi._core._BaseROM("cB")
        with pytest.raises(ValueError) as ex:
            model._check_inputargs(None, 'U')
        assert ex.value.args[0] == \
            "argument 'U' required since 'B' in modelform"

        # Try with has_inputs = False but with inputs.
        model.modelform = "cA"
        with pytest.raises(ValueError) as ex:
            model._check_inputargs(1, 'u')
        assert ex.value.args[0] == \
            "argument 'u' invalid since 'B' in modelform"


class TestContinuousROM:
    """Test _core._ContinuousROM."""
    def test_construct_f_(self):
        """Test incorrect usage of BaseContinuousROM._construct_f_()."""
        model = roi._core._ContinuousROM('')

        model.modelform = "cA"
        with pytest.raises(RuntimeError) as ex:
            model._construct_f_(lambda t: 1)
        assert ex.value.args[0] == "improper use of _construct_f_()!"

        model.modelform = "cHB"
        with pytest.raises(RuntimeError) as ex:
            model._construct_f_()
        assert ex.value.args[0] == "improper use of _construct_f_()!"

    def test_str(self):
        """Test BaseContinuousROM.__str__() (string representation)."""
        model = roi._core._ContinuousROM('')

        model.modelform = "A"
        assert str(model) == \
            "Reduced-order model structure: dx / dt = Ax(t)"
        model.modelform = "cA"
        assert str(model) == \
            "Reduced-order model structure: dx / dt = c + Ax(t)"
        model.modelform = "HB"
        assert str(model) == \
            "Reduced-order model structure: dx / dt = H(x ⊗ x)(t) + Bu(t)"
        model.modelform = "cAH"
        assert str(model) == \
            "Reduced-order model structure: dx / dt = c + Ax(t) + H(x ⊗ x)(t)"

    def test_fit(self):
        """Test _core._ContinuousROM.fit()."""
        model = roi._core._ContinuousROM("A")
        with pytest.raises(NotImplementedError) as ex:
            model.fit()
        assert ex.value.args[0] == \
            "fit() must be implemented by child classes"

        with pytest.raises(NotImplementedError) as ex:
            model.fit(1, 2, 3, 4, 5, 6, 7, a=8)
        assert ex.value.args[0] == \
            "fit() must be implemented by child classes"

    def test_predict(self):
        """Test _core._ContinuousROM.predict()."""
        model = roi._core._ContinuousROM('')

        # Get test data.
        n, k, m, r = 200, 100, 20, 10
        X, Xdot, U = _get_data(n, k, m)
        Vr = la.svd(X)[0][:,:r]
        U1d = np.ones(k)

        # Get test (reduced) operators.
        c, A, H, Hc, B = _get_operators(r, m)
        B1d = B[:,0]

        nt = 5
        x0 = X[:,0]
        t = np.linspace(0, .01*nt, nt)
        u = lambda t: np.ones(m)
        Upred = np.ones((m, nt))

        # Try to predict with invalid initial condition.
        x0_ = Vr.T @ x0
        model = _trainedmodel(True, "cAHB", Vr, m)
        with pytest.raises(ValueError) as ex:
            model.predict(x0_, t, u)
        assert ex.value.args[0] == f"invalid initial state size ({r} != {n})"

        # Try to predict with bad time array.
        with pytest.raises(ValueError) as ex:
            model.predict(x0, np.vstack((t,t)), u)
        assert ex.value.args[0] == "time 't' must be one-dimensional"

        # Predict without inputs.
        for form in _MODEL_FORMS:
            if "B" not in form:
                model = _trainedmodel(True, form, Vr, None)
                model.predict(x0, t)

        # Try to predict with badly-shaped discrete inputs.
        model = _trainedmodel(True, "cAHB", Vr, m)
        with pytest.raises(ValueError) as ex:
            model.predict(x0, t, np.random.random((m-1, nt)))
        assert ex.value.args[0] == \
            f"invalid input shape ({(m-1,nt)} != {(m,nt)}"

        model = _trainedmodel(True, "cAHB", Vr, m=1)
        with pytest.raises(ValueError) as ex:
            model.predict(x0, t, np.random.random((2, nt)))
        assert ex.value.args[0] == \
            f"invalid input shape ({(2,nt)} != {(1,nt)}"

        # Try to predict with badly-shaped continuous inputs.
        model = _trainedmodel(True, "cAHB", Vr, m)
        with pytest.raises(ValueError) as ex:
            model.predict(x0, t, lambda t: np.ones(m-1))
        assert ex.value.args[0] == \
            f"input function u() must return ndarray of shape (m,)={(m,)}"
        with pytest.raises(ValueError) as ex:
            model.predict(x0, t, lambda t: 1)
        assert ex.value.args[0] == \
            f"input function u() must return ndarray of shape (m,)={(m,)}"

        model = _trainedmodel(True, "cAHB", Vr, m=1)
        with pytest.raises(ValueError) as ex:
            model.predict(x0, t, u)
        assert ex.value.args[0] == \
            f"input function u() must return ndarray of shape (m,)={(1,)}" \
            " or scalar"

        # Try to predict with continuous inputs with bad return type
        model = _trainedmodel(True, "cAHB", Vr, m)
        with pytest.raises(ValueError) as ex:
            model.predict(x0, t, lambda t: set([5]))
        assert ex.value.args[0] == \
            f"input function u() must return ndarray of shape (m,)={(m,)}"


        for form in _MODEL_FORMS:
            if "B" in form:
                # Predict with 2D inputs.
                model = _trainedmodel(True, form, Vr, m)
                # continuous input.
                out = model.predict(x0, t, u)
                assert isinstance(out, np.ndarray)
                assert out.shape == (n,nt)
                # discrete input.
                out = model.predict(x0, t, Upred)
                assert isinstance(out, np.ndarray)
                assert out.shape == (n,nt)

                # Predict with 1D inputs.
                model = _trainedmodel(True, form, Vr, 1)
                # continuous input.
                out = model.predict(x0, t, lambda t: 1)
                assert isinstance(out, np.ndarray)
                assert out.shape == (n,nt)
                out = model.predict(x0, t, lambda t: np.array([1]))
                assert isinstance(out, np.ndarray)
                assert out.shape == (n,nt)
                # discrete input.
                out = model.predict(x0, t, np.ones_like(t))
                assert isinstance(out, np.ndarray)
                assert out.shape == (n,nt)


# Mixin classes ===============================================================
class TestInferredMixin:
    def test_check_training_data_shapes(self):
        """Test _core._InferredMixin._check_training_data_shapes()."""
        # Get test data.
        n, k, m, r = 200, 100, 20, 10
        X, Xdot, U = _get_data(n, k, m)
        Vr = la.svd(X)[0][:,:r]
        model = roi._core._InferredMixin()

        # Try to fit the model with misaligned X and Xdot.
        with pytest.raises(ValueError) as ex:
            model._check_training_data_shapes(X, Xdot[:,1:-1], Vr)
        assert ex.value.args[0] == \
            f"shape of X != shape of Xdot ({(n,k)} != {(n,k-2)})"

        # Try to fit the model with misaligned X and Vr.
        with pytest.raises(ValueError) as ex:
            model._check_training_data_shapes(X, Xdot, Vr[1:-1,:])
        assert ex.value.args[0] == \
            f"X and Vr not aligned, first dimension {n} != {n-2}"


class TestIntrusiveMixin:
    def test_check_operators(self):
        model = roi._core._IntrusiveMixin()
        model.modelform = "cAHB"
        v = None

        # Try with missing operator keys.
        with pytest.raises(KeyError) as ex:
            model._check_operators({"A":v, "H":v, "B":v})
        assert ex.value.args[0] == "missing operator key 'c'"

        with pytest.raises(KeyError) as ex:
            model._check_operators({"H":v, "B":v})
        assert ex.value.args[0] == "missing operator keys 'c', 'A'"

        # Try with surplus operator keys.
        with pytest.raises(KeyError) as ex:
            model._check_operators({'CC':v, "c":v, "A":v, "H":v, "B":v})
        assert ex.value.args[0] == "invalid operator key 'CC'"

        with pytest.raises(KeyError) as ex:
            model._check_operators({"c":v, "A":v, "H":v, "B":v,
                                    'CC':v, 'LL':v})
        assert ex.value.args[0] == "invalid operator keys 'CC', 'LL'"

        # Correct usage.
        model._check_operators({"c":v, "A":v, "H":v, "B":v})


class TestAffineMixin:
    def test_check_affines(self):
        model = roi._core._AffineMixin()
        model.modelform = "cAHB"
        v = [lambda s: 0, lambda s: 0]

        # Try with surplus affine keys.
        with pytest.raises(KeyError) as ex:
            model._check_affines({'CC':v, "c":v, "A":v, "H":v, "B":v}, 0)
        assert ex.value.args[0] == "invalid affine key 'CC'"

        with pytest.raises(KeyError) as ex:
            model._check_affines({"c":v, "A":v, "H":v, "B":v,
                                    'CC':v, 'LL':v}, 0)
        assert ex.value.args[0] == "invalid affine keys 'CC', 'LL'"

        # Correct usage.
        model._check_affines({"c":v, "H":v}, 0)     # OK to be missing some.
        model._check_affines({"c":v, "A":v, "H":v, "B":v}, 0)


# Useable classes =============================================================

# Continuous models (i.e., solving dx/dt = f(t,x,u)) --------------------------
class TestInferredContinuousROM:
    """Test _core.InferredContinuousROM."""
    def test_fit(self):
        model = roi.InferredContinuousROM("cAH")

        # Get test data.
        n, k, m, r = 200, 100, 20, 10
        X, Xdot, U = _get_data(n, k, m)
        Vr = la.svd(X)[0][:,:r]

        # Fit the model with each possible modelform.
        for form in _MODEL_FORMS:
            if "B" not in form:
                model.modelform = form
                model.fit(X, Xdot, Vr)

        # Test fit output sizes.
        model.modelform = "cAHB"
        model.fit(X, Xdot, Vr, U=U)
        assert model.n == n
        assert model.r == r
        assert model.m == m
        assert model.A_.shape == (r,r)
        assert model.Hc_.shape == (r,r*(r+1)//2)
        assert model.H_.shape == (r,r**2)
        assert model.c_.shape == (r,)
        assert model.B_.shape == (r,m)
        assert hasattr(model, "residual_")

        # Try again with one-dimensional inputs.
        m = 1
        U = np.ones(k)
        model.fit(X, Xdot, Vr, U=U)
        n, r, m = model.n, model.r, model.m
        assert model.n == n
        assert model.r == r
        assert model.m == 1
        assert model.A_.shape == (r,r)
        assert model.Hc_.shape == (r,r*(r+1)//2)
        assert model.H_.shape == (r,r**2)
        assert model.c_.shape == (r,)
        assert model.B_.shape == (r,1)
        assert hasattr(model, "residual_")


class TestIntrusiveContinuousROM:
    """Test _core.IntrusiveContinuousROM."""

    def test_fit(self):
        model = roi.IntrusiveContinuousROM("cAHB")

        # Get test data.
        n, k, m, r = 200, 100, 20, 10
        X, Xdot, U = _get_data(n, k, m)
        Vr = la.svd(X)[0][:,:r]

        # Get test operators.
        c, A, H, Hc, B = _get_operators(n, m)
        B1d = B[:,0]
        operators = {"c":c, "A":A, "H":H, "B":B}

        # Try to fit the model with misaligned operators and Vr.
        Abad = A[:,:-2]
        Hbad = H[:,1:]
        cbad = c[::2]
        Bbad = B[1:,:]

        with pytest.raises(ValueError) as ex:
            model.fit({"c":cbad, "A":A, "H":H, "B":B}, Vr)
        assert ex.value.args[0] == "basis Vr and FOM operator c not aligned"

        with pytest.raises(ValueError) as ex:
            model.fit({"c":c, "A":Abad, "H":H, "B":B}, Vr)
        assert ex.value.args[0] == "basis Vr and FOM operator A not aligned"

        with pytest.raises(ValueError) as ex:
            model.fit({"c":c, "A":A, "H":Hbad, "B":B}, Vr)
        assert ex.value.args[0] == \
            "basis Vr and FOM operator H not aligned"

        with pytest.raises(ValueError) as ex:
            model.fit({"c":c, "A":A, "H":H, "B":Bbad}, Vr)
        assert ex.value.args[0] == "basis Vr and FOM operator B not aligned"

        # Fit the model with each possible modelform.
        for form in ["A", "cA", "H", "cH", "AH", "cAH", "cAHB"]:
            model.modelform = form
            ops = {key:val for key,val in operators.items() if key in form}
            model.fit(ops, Vr)

        model.modelform = "cAHB"
        model.fit({"c":c, "A":A, "H":Hc, "B":B}, Vr)

        # Test fit output sizes.
        assert model.n == n
        assert model.r == r
        assert model.m == m
        assert model.A.shape == (n,n)
        assert model.Hc.shape == (n,n*(n+1)//2)
        assert model.H.shape == (n,n**2)
        assert model.c.shape == (n,)
        assert model.B.shape == (n,m)
        assert model.A_.shape == (r,r)
        assert model.Hc_.shape == (r,r*(r+1)//2)
        assert model.H_.shape == (r,r**2)
        assert model.c_.shape == (r,)
        assert model.B_.shape == (r,m)

        # Fit the model with 1D inputs (1D array for B)
        model.modelform = "cAHB"
        model.fit({"c":c, "A":A, "H":H, "B":B1d}, Vr)
        assert model.B.shape == (n,1)
        assert model.B_.shape == (r,1)


class TestInterpolatedInferredContinuousROM:
    """Test _core.InterpolatedInferredContinuousROM."""
    def test_fit(self):
        """Test _core.InterpolatedInferredContinuousROM.fit()."""
        model = roi.InterpolatedInferredContinuousROM("cAH")

        # Get data for fitting.
        n, m, k, r = 50, 10, 20, 5
        X1, Xdot1, U1 = _get_data(n, k, m)
        X2, Xdot2, U2 = X1+1, Xdot1.copy(), U1+1
        Xs = [X1, X2]
        Xdots = [Xdot1, Xdot2]
        Us = [U1, U2]
        ps = [1, 2]
        Vr = la.svd(np.hstack(Xs))[0][:,:r]

        # Try with non-scalar parameters.
        with pytest.raises(ValueError) as ex:
            model.fit([np.array([1,1]), np.array([2,2])], Xs, Xdots, Vr)
        assert ex.value.args[0] == "only scalar parameter values are supported"

        # Try with bad number of Xs.
        with pytest.raises(ValueError) as ex:
            model.fit(ps, [X1, X2, X2+1], Xdots, Vr)
        assert ex.value.args[0] == \
            "num parameter samples != num state snapshot sets (2 != 3)"

        # Try with bad number of Xdots.
        with pytest.raises(ValueError) as ex:
            model.fit(ps, Xs, Xdots + [Xdot1], Vr)
        assert ex.value.args[0] == \
            "num parameter samples != num velocity snapshot sets (2 != 3)"

        # Try with varying input sizes.
        model.modelform = "cAHB"
        with pytest.raises(ValueError) as ex:
            model.fit(ps, Xs, Xdots, Vr, [U1, U2[:-1]])
        assert ex.value.args[0] == \
            "shape of 'U' inconsistent across samples"

        # Fit correctly with no inputs.
        model.modelform = "cAH"
        model.fit(ps, Xs, Xdots, Vr)
        for attr in ["models_", "dataconds_", "residuals_", "fs_"]:
            assert hasattr(model, attr)
            assert len(getattr(model, attr)) == len(model.models_)

        # Fit correctly with inputs.
        model.modelform = "cAHB"
        model.fit(ps, Xs, Xdots, Vr, Us)

        assert len(model) == len(ps)

    def test_predict(self):
        """Test _core.InterpolatedInferredContinuousROM.predict()."""
        model = roi.InterpolatedInferredContinuousROM("cAH")

        # Get data for fitting.
        n, m, k, r = 50, 10, 20, 5
        X1, Xdot1, U1 = _get_data(n, k, m)
        X2, Xdot2, U2 = X1+1, Xdot1.copy(), U1+1
        Xs = [X1, X2]
        Xdots = [Xdot1, Xdot2]
        Us = [U1, U2]
        ps = [1, 2]
        Vr = la.svd(np.hstack(Xs))[0][:,:r]

        # Parameters for predicting.
        x0 = np.random.random(n)
        nt = 5
        t = np.linspace(0, .01*nt, nt)
        u = lambda t: np.ones(10)

        # Fit / predict with no inputs.
        model.fit(ps, Xs, Xdots, Vr)
        model.predict(1, x0, t)
        model.predict(1.5, x0, t)

        # Fit / predict with inputs.
        model.modelform = "cAHB"
        model.fit(ps, Xs, Xdots, Vr, Us)
        model.predict(1, x0, t, u)
        model.predict(1.5, x0, t, u)


# Discrete ROMs (i.e., solving x_{k+1} = f(x_{k},u_{k})) --------------------
