// A small KerML (kernel modeling language) example.
// The longeron package parses and validates KerML; model building targets SysML.
package Kernel {
    doc /* Minimal kernel library sketch. */

    abstract classifier Anything;

    class Occurrence specializes Anything {
        feature startShot : Occurrence[1];
        feature endShot : Occurrence[1];
    }

    datatype ScalarValue;
    datatype NumericalValue specializes ScalarValue;

    classifier Vehicle specializes Anything {
        feature mass : NumericalValue[1];
        feature wheels : Wheel[4] ordered;
    }

    classifier Wheel specializes Anything;

    assoc Ownership {
        end feature owner : Anything[1];
        end feature owned : Anything[0..*];
    }

    function Plus {
        in feature x : NumericalValue[1];
        in feature y : NumericalValue[1];
        return result : NumericalValue[1];
    }
}
