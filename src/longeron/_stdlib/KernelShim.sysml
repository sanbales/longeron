standard library package KernelShim {
    doc /* Stand-ins for the KerML Kernel Library names that user models and
           the vendored Systems Library reference. KerML is parse-only in
           the longeron package, so the real kernel packages cannot be model-
           built; these shims make the common names resolvable. */
}

standard library package ScalarValues {
    abstract attribute def ScalarValue;
    abstract attribute def DataValue;
    attribute def Boolean :> ScalarValue;
    attribute def String :> ScalarValue;
    abstract attribute def NumericalValue :> ScalarValue;
    attribute def Number :> NumericalValue;
    attribute def Complex :> Number;
    attribute def Real :> Complex;
    attribute def Rational :> Real;
    attribute def Integer :> Rational;
    attribute def Natural :> Integer;
    attribute def Positive :> Natural;
}

standard library package Base {
    abstract item def Anything;
    abstract item things : Anything [0..*];
    abstract item def DataItem :> Anything;
}

standard library package Occurrences {
    abstract occurrence def Occurrence;
    abstract occurrence occurrences : Occurrence [0..*];
    abstract occurrence def Life :> Occurrence;
}

standard library package Objects {
    abstract item def Object;
    abstract item objects : Object [0..*];
}

standard library package Performances {
    abstract occurrence def Performance;
    abstract occurrence performances : Performance [0..*];
    abstract occurrence def BooleanEvaluation :> Performance;
    abstract occurrence def Evaluation :> Performance;
}

standard library package Collections {
    abstract item def Collection;
    item def OrderedCollection :> Collection;
    item def List :> OrderedCollection;
    item def Set :> Collection;
    item def Bag :> Collection;
    item def Array :> OrderedCollection;
}

standard library package Links {
    abstract item def Link;
    abstract item links : Link [0..*];
    abstract item def BinaryLink :> Link;
}

standard library package Transfers {
    abstract occurrence def Transfer;
    abstract occurrence transfers : Transfer [0..*];
}

standard library package ScalarFunctions {
    doc /* Kernel scalar functions (abs, max, ...) are interpreter builtins in
           longeron; the package name exists so imports of it resolve
           (TradeStudies imports it). */
}

standard library package ControlFunctions {
    doc /* Kernel control functions (collection -> operators) are interpreter
           builtins in longeron; the package name exists so imports of it
           resolve (TradeStudies imports it). */
}
