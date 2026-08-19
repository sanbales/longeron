grammar KerML;

// ===== Parser Rules =====

// 8.2.2.7 Special lexical terminals (keyword/symbol equivalents)
// These allow either symbolic or keyword forms for convenience

// TYPED_BY = ':' | 'typed' 'by'
typedByToken
    : COLON
    | TYPED BY
    ;

// SPECIALIZES = ':>' | 'specializes'
specializesToken
    : COLON_GT
    | SPECIALIZES
    ;

// SUBSETS = ':>' | 'subsets'
subsetsToken
    : COLON_GT
    | SUBSETS
    ;

// REFERENCES = '::>' | 'references'
referencesToken
    : DOUBLE_COLON_GT
    | REFERENCES
    ;

// CROSSES = '=>' | 'crosses'
crossesToken
    : EQUALS_GT
    | CROSSES
    ;

// REDEFINES = ':>>' | 'redefines'
redefinesToken
    : COLON_GT_GT
    | REDEFINES
    ;

// CONJUGATES = '~' | 'conjugates'
conjugatesToken
    : TILDE
    | CONJUGATES
    ;

// 8.2.3 Root Concrete Syntax
// 8.2.3.1 Elements and Relationships Concrete Syntax

// Identification : Element =
//     ( '<' declaredShortName = NAME '>' )?
//     ( declaredName = NAME )?
identification
    : ( LESS declaredShortName=NAME GREATER )?
      ( declaredName=NAME )?
    ;

// RelationshipBody : Relationship =
//     ';' | '{' RelationshipOwnedElement* '}'
relationshipBody
    : SEMICOLON
    | LBRACE relationshipOwnedElement* RBRACE
    ;

// RelationshipOwnedElement : Relationship =
//     ownedRelatedElement += OwnedRelatedElement
//     | ownedRelationship += OwnedAnnotation
relationshipOwnedElement
    : ownedRelatedElement
    | ownedAnnotation
    ;

// OwnedRelatedElement : Element =
//     NonFeatureElement | FeatureElement
ownedRelatedElement
    : nonFeatureElement
    | featureElement
    ;

// 8.2.3.2 Dependencies Concrete Syntax

// Dependency =
//     ( ownedRelationship += PrefixMetadataAnnotation )*
//     'dependency' ( Identification? 'from' )?
//     client += [QualifiedName] ( ',' client += [QualifiedName] )* 'to'
//     supplier += [QualifiedName] ( ',' supplier += [QualifiedName] )*
//     RelationshipBody
dependency
    : prefixMetadataAnnotation*
      DEPENDENCY ( identification? FROM )?
      client+=qualifiedName ( COMMA client+=qualifiedName )* TO
      supplier+=qualifiedName ( COMMA supplier+=qualifiedName )*
      relationshipBody
    ;

// 8.2.3.3 Annotations Concrete Syntax
// 8.2.3.3.1 Annotations

// Annotation =
//     annotatedElement = [QualifiedName]
annotation
    : annotatedElement=qualifiedName
    ;

// OwnedAnnotation : Annotation =
//     ownedRelatedElement += AnnotatingElement
ownedAnnotation
    : annotatingElement
    ;

// AnnotatingElement =
//     Comment
//     | Documentation
//     | TextualRepresentation
//     | MetadataFeature
annotatingElement
    : comment
    | documentation
    | textualRepresentation
    | metadataFeature
    ;

// 8.2.3.3.2 Comments and Documentation

// Comment =
//     ( 'comment' Identification
//       ( 'about' ownedRelationship += Annotation
//         ( ',' ownedRelationship += Annotation )*
//       )?
//     )?
//     ( 'locale' locale = STRING_VALUE )?
//     body = REGULAR_COMMENT
comment
    : ( COMMENT identification
        ( ABOUT ownedRelationship+=annotation
          ( COMMA ownedRelationship+=annotation )*
        )?
      )?
      ( LOCALE locale=STRING_VALUE )?
      body=REGULAR_COMMENT
    ;

// Documentation =
//     'doc' Identification
//     ( 'locale' locale = STRING_VALUE )?
//     body = REGULAR_COMMENT
documentation
    : DOC identification
      ( LOCALE locale=STRING_VALUE )?
      body=REGULAR_COMMENT
    ;

// 8.2.3.3.3 Textual Representation

// TextualRepresentation =
//     ( 'rep' Identification )?
//     'language' language = STRING_VALUE
//     body = REGULAR_COMMENT
textualRepresentation
    : ( REP identification )?
      LANGUAGE language=STRING_VALUE
      body=REGULAR_COMMENT
    ;

// 8.2.3.4 Namespaces Concrete Syntax
// 8.2.3.4.1 Namespaces

// RootNamespace : Namespace =
//     NamespaceBodyElement*
rootNamespace
    : namespaceBodyElement*
    ;

// Namespace =
//     ( ownedRelationship += PrefixMetadataMember )*
//     NamespaceDeclaration NamespaceBody
namespace
    : prefixMetadataMember*
      namespaceDeclaration namespaceBody
    ;

// NamespaceDeclaration : Namespace =
//     'namespace' Identification
namespaceDeclaration
    : NAMESPACE identification
    ;

// NamespaceBody : Namespace =
//     ';' | '{' NamespaceBodyElement* '}'
namespaceBody
    : SEMICOLON
    | LBRACE namespaceBodyElement* RBRACE
    ;

// NamespaceBodyElement : Namespace =
//     ownedRelationship += NamespaceMember
//     | ownedRelationship += AliasMember
//     | ownedRelationship += Import
namespaceBodyElement
    : namespaceMember
    | aliasMember
    | import_
    | REGULAR_COMMENT  // Allow standalone comments in namespace body
    ;

// MemberPrefix : Membership =
//     ( visibility = VisibilityIndicator )?
memberPrefix
    : visibilityIndicator?
    ;

// VisibilityIndicator : VisibilityKind =
//     'public' | 'private' | 'protected'
visibilityIndicator
    : PUBLIC
    | PRIVATE
    | PROTECTED
    ;

// NamespaceMember : OwningMembership =
//     NonFeatureMember
//     | NamespaceFeatureMember
namespaceMember
    : nonFeatureMember
    | namespaceFeatureMember
    ;

// NonFeatureMember : OwningMembership =
//     MemberPrefix
//     ownedRelatedElement += MemberElement
nonFeatureMember
    : memberPrefix
      memberElement
    ;

// NamespaceFeatureMember : OwningMembership =
//     MemberPrefix
//     ownedRelatedElement += FeatureElement
namespaceFeatureMember
    : memberPrefix
      featureElement
    ;

// AliasMember : Membership =
//     MemberPrefix
//     'alias' ( '<' memberShortName = NAME '>' )?
//     ( memberName = NAME )?
//     'for' memberElement = [QualifiedName]
//     RelationshipBody
aliasMember
    : memberPrefix
      ALIAS ( LESS memberShortName=NAME GREATER )?
      ( memberName=NAME )?
      FOR memberEl=qualifiedName
      relationshipBody
    ;

// QualifiedName =
//     ( '$' '::' )? ( NAME '::' )* NAME
qualifiedName
    : ( DOLLAR DOUBLE_COLON )?
      ( NAME DOUBLE_COLON )*
      NAME
    ;

// 8.2.3.4.2 Imports

// Import =
//     visibility = VisibilityIndicator
//     'import' ( isImportAll ?= 'all' )?
//     ImportDeclaration RelationshipBody
//
// Rule we've adopted for import visibility:
//   - Explicit `private` / `public` / `protected` keyword → that visibility.
//   - Omitted keyword → `private` (matches the abstract-syntax default per
//     KerML 7.2.5.4 ¶393).
// Rationale: this satisfies both the ¶393 normative sentence ("always shown
// explicitly") — because strict authors always write the keyword and get what
// they wrote — AND the spec's own omitted-keyword example at ¶346 — because
// that form parses and gets `private`, the same result strict authors get
// when they type `private import X;`. See SPEC-ISSUES.md #25.
import_
    : memberPrefix
      IMPORT ( isImportAll=ALL )?
      importDeclaration relationshipBody
    ;

// ImportDeclaration : Import
//     MembershipImport | NamespaceImport
importDeclaration
    : membershipImport
    | namespaceImport
    ;

// MembershipImport =
//     importedMembership = [QualifiedName]
//     ( '::' isRecursive ?= '**' )?
membershipImport
    : importedMembership=qualifiedName
      ( DOUBLE_COLON isRecursive=DOUBLE_STAR )?
    ;

// NamespaceImport =
//     importedNamespace = [QualifiedName] '::' '*'
//     ( '::' isRecursive ?= '**' )?
//     | importedNamespace = FilterPackage
//       { ownedRelatedElement += importedNamespace }
namespaceImport
    : qualifiedName DOUBLE_COLON STAR
      ( DOUBLE_COLON isRecursive=DOUBLE_STAR )?
    | filterPackageImport
    ;

// FilterPackage : Package =
//     ownedRelationship += ImportDeclaration
//     ( ownedRelationship += FilterPackageMember )+
// Inlined to avoid left recursion with importDeclaration
filterPackageImport
    : ( membershipImport | qualifiedName DOUBLE_COLON STAR ( DOUBLE_COLON isRecursive=DOUBLE_STAR )? )
      filterPackageMember+
    ;

// FilterPackageMember : ElementFilterMembership =
//     '[' ownedRelatedElement += OwnedExpression ']'
filterPackageMember
    : LBRACKET ownedExpression RBRACKET
    ;

// 8.2.3.4.3 Namespace Elements

// MemberElement : Element =
//     AnnotatingElement | NonFeatureElement
memberElement
    : annotatingElement
    | nonFeatureElement
    ;

// NonFeatureElement : Element =
//     Dependency | Namespace | Type | Classifier | DataType | Class | Structure
//     | Metaclass | Association | AssociationStructure | Interaction | Behavior
//     | Function | Predicate | Multiplicity | Package | LibraryPackage
//     | Specialization | Conjugation | Subclassification | Disjoining
//     | FeatureInverting | FeatureTyping | Subsetting | Redefinition | TypeFeaturing
nonFeatureElement
    : dependency
    | namespace
    | type
    | classifier
    | datatype
    | class
    | structure
    | metaclass
    | association
    | associationStructure
    | interaction
    | behavior
    | function
    | predicate
    | multiplicity
    | package
    | libraryPackage
    | rendering
    | specialization
    | conjugation
    | subclassification
    | disjoining
    | featureInverting
    | featureTyping
    | subsetting
    | redefinition
    | typeFeaturing
    | view
    | viewpoint
    ;

// FeatureElement : Feature =
//     Feature | Step | Expression | BooleanExpression | Invariant
//     | Connector | BindingConnector | Succession | Flow | SuccessionFlow
featureElement
    : feature
    | step
    | expression
    | booleanExpression
    | invariant
    | connector
    | bindingConnector
    | succession
    | flow
    | successionFlow
    ;

// 8.2.4 Core Concrete Syntax
// 8.2.4.1 Types Concrete Syntax
// 8.2.4.1.1 Types

// Type =
//     TypePrefix 'type'
//     TypeDeclaration TypeBody
type
    : typePrefix TYPE
      typeDeclaration typeBody
    ;

// TypePrefix : Type =
//     ( isAbstract ?= 'abstract' )?
//     ( ownedRelationship += PrefixMetadataMember )*
typePrefix
    : ( isAbstract=ABSTRACT )?
      prefixMetadataMember*
    ;

// TypeDeclaration : Type =
//     ( isSufficient ?= 'all' )? Identification
//     ( ownedRelationship += OwnedMultiplicity )?
//     ( SpecializationPart | ConjugationPart )+
//     TypeRelationshipPart*
typeDeclaration
    : ( isSufficient=ALL )? identification
      ownedMultiplicity?
      ( specializationPart | conjugationPart )+
      typeRelationshipPart*
    ;

// SpecializationPart : Type =
//     SPECIALIZES ownedRelationship += OwnedSpecialization
//     ( ',' ownedRelationship += OwnedSpecialization )*
specializationPart
    : specializesToken ownedSpecialization
      ( COMMA ownedSpecialization )*
    ;

// ConjugationPart : Type =
//     CONJUGATES ownedRelationship += OwnedConjugation
conjugationPart
    : conjugatesToken ownedConjugation
    ;

// TypeRelationshipPart : Type =
//     DisjoiningPart
//     | UnioningPart
//     | IntersectingPart
//     | DifferencingPart
typeRelationshipPart
    : disjoiningPart
    | unioningPart
    | intersectingPart
    | differencingPart
    ;

// DisjoiningPart : Type =
//     'disjoint' 'from' ownedRelationship += OwnedDisjoining
//     ( ',' ownedRelationship += OwnedDisjoining )*
disjoiningPart
    : DISJOINT FROM ownedDisjoining
      ( COMMA ownedDisjoining )*
    ;

// UnioningPart : Type =
//     'unions' ownedRelationship += Unioning
//     ( ',' ownedRelationship += Unioning )*
unioningPart
    : UNIONS unioning
      ( COMMA unioning )*
    ;

// IntersectingPart : Type =
//     'intersects' ownedRelationship += Intersecting
//     ( ',' ownedRelationship += Intersecting )*
intersectingPart
    : INTERSECTS intersecting
      ( COMMA intersecting )*
    ;

// DifferencingPart : Type =
//     'differences' ownedRelationship += Differencing
//     ( ',' ownedRelationship += Differencing )*
differencingPart
    : DIFFERENCES differencing
      ( COMMA differencing )*
    ;

// TypeBody : Type =
//     ';' | '{' TypeBodyElement* '}'
typeBody
    : SEMICOLON
    | LBRACE typeBodyElement* RBRACE
    ;

// TypeBodyElement : Type =
//     ownedRelationship += NonFeatureMember
//     | ownedRelationship += FeatureMember
//     | ownedRelationship += AliasMember
//     | ownedRelationship += Import
typeBodyElement
    : nonFeatureMember
    | featureMember
    | aliasMember
    | import_
    | REGULAR_COMMENT  // Allow standalone comments in type body
    ;

// 8.2.4.1.2 Specialization

// Specialization =
//     ( 'specialization' Identification )?
//     'subtype' SpecificType
//     SPECIALIZES GeneralType
//     RelationshipBody
specialization
    : ( SPECIALIZATION identification )?
      SUBTYPE specificType
      specializesToken generalType
      relationshipBody
    ;

// OwnedSpecialization : Specialization =
//     GeneralType
ownedSpecialization
    : generalType
    ;

// SpecificType : Specialization :
//     specific = [QualifiedName]
//     | specific += OwnedFeatureChain
//       { ownedRelatedElement += specific }
specificType
    : qualifiedName
    | ownedFeatureChain
    ;

// GeneralType : Specialization =
//     general = [QualifiedName]
//     | general += OwnedFeatureChain
//       { ownedRelatedElement += general }
generalType
    : qualifiedName
    | ownedFeatureChain
    ;

// 8.2.4.1.3 Conjugation

// Conjugation =
//     ( 'conjugation' Identification )?
//     'conjugate'
//     ( conjugatedType = [QualifiedName]
//       | conjugatedType = FeatureChain
//         { ownedRelatedElement += conjugatedType }
//     )
//     CONJUGATES
//     ( originalType = [QualifiedName]
//       | originalType = FeatureChain
//         { ownedRelatedElement += originalType }
//     )
//     RelationshipBody
conjugation
    : ( CONJUGATION identification )?
      CONJUGATE
      ( qualifiedName
      | featureChain
      )
      conjugatesToken
      ( qualifiedName
      | featureChain
      )
      relationshipBody
    ;

// OwnedConjugation : Conjugation =
//     originalType = [QualifiedName]
//     | originalType = FeatureChain
//       { ownedRelatedElement += originalType }
ownedConjugation
    : qualifiedName
    | featureChain
    ;

// 8.2.4.1.4 Disjoining

// Disjoining =
//     ( 'disjoining' Identification )?
//     'disjoint'
//     ( typeDisjoined = [QualifiedName]
//       | typeDisjoined = FeatureChain
//         { ownedRelatedElement += typeDisjoined }
//     )
//     'from'
//     ( disjoiningType = [QualifiedName]
//       | disjoiningType = FeatureChain
//         { ownedRelatedElement += disjoiningType }
//     )
//     RelationshipBody
disjoining
    : ( DISJOINING identification )?
      DISJOINT
      ( qualifiedName
      | featureChain
      )
      FROM
      ( qualifiedName
      | featureChain
      )
      relationshipBody
    ;

// OwnedDisjoining : Disjoining =
//     disjoiningType = [QualifiedName]
//     | disjoiningType = FeatureChain
//       { ownedRelatedElement += disjoiningType }
ownedDisjoining
    : qualifiedName
    | featureChain
    ;

// 8.2.4.1.5 Unioning, Intersecting and Differencing

// Unioning =
//     unioningType = [QualifiedName]
//     | ownedRelatedElement += OwnedFeatureChain
unioning
    : unioningType=qualifiedName
    | ownedFeatureChain
    ;

// Intersecting =
//     intersectingType = [QualifiedName]
//     | ownedRelatedElement += OwnedFeatureChain
intersecting
    : intersectingType=qualifiedName
    | ownedFeatureChain
    ;

// Differencing =
//     differencingType = [QualifiedName]
//     | ownedRelatedElement += OwnedFeatureChain
differencing
    : differencingType=qualifiedName
    | ownedFeatureChain
    ;

// 8.2.4.1.6 Feature Membership

// FeatureMember : OwningMembership =
//     TypeFeatureMember
//     | OwnedFeatureMember
featureMember
    : typeFeatureMember
    | ownedFeatureMember
    ;

// TypeFeatureMember : OwningMembership =
//     MemberPrefix 'member' ownedRelatedElement += FeatureElement
typeFeatureMember
    : memberPrefix MEMBER featureElement
    ;

// OwnedFeatureMember : FeatureMembership =
//     MemberPrefix ownedRelatedElement += FeatureElement
ownedFeatureMember
    : memberPrefix featureElement
    ;

// 8.2.4.2 Classifiers Concrete Syntax
// 8.2.4.2.1 Classifiers

// Classifier =
//     TypePrefix 'classifier'
//     ClassifierDeclaration TypeBody
classifier
    : typePrefix CLASSIFIER
      classifierDeclaration typeBody
    ;

// ClassifierDeclaration : Classifier =
//     ( isSufficient ?= 'all' )? Identification
//     ( ownedRelationship += OwnedMultiplicity )?
//     ( SuperclassingPart | ConjugationPart )?
//     TypeRelationshipPart*
classifierDeclaration
    : ( isSufficient=ALL )? identification
      ownedMultiplicity?
      ( superclassingPart | conjugationPart )?
      typeRelationshipPart*
    ;

// SuperclassingPart : Classifier =
//     SPECIALIZES ownedRelationship += OwnedSubclassification
//     ( ',' ownedRelationship += OwnedSubclassification )*
superclassingPart
    : specializesToken ownedSubclassification
      ( COMMA ownedSubclassification )*
    ;

// 8.2.4.2.2 Subclassification

// Subclassification =
//     ( 'specialization' Identification )?
//     'subclassifier' subclassifier = [QualifiedName]
//     SPECIALIZES superclassifier = [QualifiedName]
//     RelationshipBody
subclassification
    : ( SPECIALIZATION identification )?
      SUBCLASSIFIER subclassifier=qualifiedName
      specializesToken superclassifier=qualifiedName
      relationshipBody
    ;

// OwnedSubclassification : Subclassification =
//     superclassifier = [QualifiedName]
ownedSubclassification
    : superclassifier=qualifiedName
    ;

// 8.2.4.3 Features Concrete Syntax
// 8.2.4.3.1 Features

// Feature =
//     ( FeaturePrefix
//       ( 'feature' | ownedRelationship += PrefixMetadataMember )
//       FeatureDeclaration?
//     )
//     | ( EndFeaturePrefix | BasicFeaturePrefix )
//       FeatureDeclaration
//     )
//     ValuePart? TypeBody
feature
    : ( featurePrefix
        ( FEATURE | prefixMetadataMember )
        featureDeclaration?
      | ( endFeaturePrefix | basicFeaturePrefix )
        featureDeclaration
      )
      valuePart? typeBody
    ;

// EndFeaturePrefix : Feature =
//     ( isConstant ?= 'const' { isVariable = true } )?
//     isEnd ?= 'end'
endFeaturePrefix
    : ( isConstant=CONST )?
      isEnd=END
    ;

// BasicFeaturePrefix : Feature :
//     ( direction = FeatureDirection )?
//     ( isDerived ?= 'derived' )?
//     ( isAbstract ?= 'abstract' )?
//     ( isComposite ?= 'composite' | isPortion ?= 'portion' )?
//     ( isVariable ?= 'var' | isConstant ?= 'const' { isVariable = true } )?
basicFeaturePrefix
    : ( direction=featureDirection )?
      ( isDerived=DERIVED )?
      ( isAbstract=ABSTRACT )?
      ( isComposite=COMPOSITE | isPortion=PORTION )?
      ( isVariable=VAR | isConstant=CONST )?
    ;

// FeaturePrefix :
//     ( EndFeaturePrefix ( ownedRelationship += OwnedCrossFeatureMember )?
//     | BasicFeaturePrefix
//     )
//     ( ownedRelationship += PrefixMetadataMember )*
featurePrefix
    : ( endFeaturePrefix ownedCrossFeatureMember?
      | basicFeaturePrefix
      )
      prefixMetadataMember*
    ;

// OwnedCrossFeatureMember : OwningMembership =
//     ownedRelatedElement += OwnedCrossFeature
ownedCrossFeatureMember
    : ownedCrossFeature
    ;

// OwnedCrossFeature : Feature =
//     BasicFeaturePrefix FeatureDeclaration
ownedCrossFeature
    : basicFeaturePrefix featureDeclaration
    ;

// FeatureDirection : FeatureDirectionKind =
//     'in' | 'out' | 'inout'
featureDirection
    : IN
    | OUT
    | INOUT
    ;

// FeatureDeclaration : Feature =
//     ( isSufficient ?= 'all' )?
//     ( FeatureIdentification
//       ( FeatureSpecializationPart | ConjugationPart )?
//     | FeatureSpecializationPart
//     | ConjugationPart
//     )
//     FeatureRelationshipPart*
featureDeclaration
    : ( isSufficient=ALL )?
      ( featureIdentification
        ( featureSpecializationPart | conjugationPart )?
      | featureSpecializationPart
      | conjugationPart
      )
      featureRelationshipPart*
    ;

// FeatureIdentification : Feature =
//     '<' declaredShortName = NAME '>' ( declaredName = NAME )?
//     | declaredName = NAME
featureIdentification
    : LESS declaredShortName=NAME GREATER ( declaredName=NAME )?
    | declaredName=NAME
    ;

// FeatureRelationshipPart : Feature =
//     TypeRelationshipPart
//     | ChainingPart
//     | InvertingPart
//     | TypeFeaturingPart
featureRelationshipPart
    : typeRelationshipPart
    | chainingPart
    | invertingPart
    | typeFeaturingPart
    ;

// ChainingPart : Feature =
//     'chains'
//     ( ownedRelationship += OwnedFeatureChaining
//       | FeatureChain )
chainingPart
    : CHAINS
      ( ownedFeatureChaining
      | featureChain
      )
    ;

// InvertingPart : Feature =
//     'inverse' 'of' ownedRelationship += OwnedFeatureInverting
invertingPart
    : INVERSE OF ownedFeatureInverting
    ;

// TypeFeaturingPart : Feature =
//     'featured' 'by' ownedRelationship += OwnedTypeFeaturing
//     ( ',' ownedRelationship += OwnedTypeFeaturing )*
typeFeaturingPart
    : FEATURED BY ownedTypeFeaturing
      ( COMMA ownedTypeFeaturing )*
    ;

// FeatureSpecializationPart : Feature =
//     FeatureSpecialization+ MultiplicityPart? FeatureSpecialization*
//     | MultiplicityPart FeatureSpecialization*
featureSpecializationPart
    : featureSpecialization+ multiplicityPart? featureSpecialization*
    | multiplicityPart featureSpecialization*
    ;

// MultiplicityPart : Feature =
//     ownedRelationship += OwnedMultiplicity
//     | ( ownedRelationship += OwnedMultiplicity )?
//       ( isOrdered ?= 'ordered' ( {isUnique = false} 'nonunique' )?
//       | {isUnique = false} 'nonunique' ( isOrdered ?= 'ordered' )? )
multiplicityPart
    : ownedMultiplicity
    | ownedMultiplicity?
      ( isOrdered=ORDERED ( isNonunique=NONUNIQUE )?
      | isNonunique=NONUNIQUE ( isOrdered=ORDERED )?
      )
    ;

// FeatureSpecialization : Feature =
//     Typings | Subsettings | References | Crosses | Redefinitions
featureSpecialization
    : typings
    | subsettings
    | references
    | crosses
    | redefinitions
    ;

// Typings : Feature =
//     TypedBy ( ',' ownedRelationship += OwnedFeatureTyping )*
typings
    : typedBy ( COMMA ownedFeatureTyping )*
    ;

// TypedBy : Feature =
//     TYPED_BY ownedRelationship += OwnedFeatureTyping
typedBy
    : typedByToken ownedFeatureTyping
    ;

// Subsettings : Feature =
//     Subsets ( ',' ownedRelationship += OwnedSubsetting )*
subsettings
    : subsets ( COMMA ownedSubsetting )*
    ;

// Subsets : Feature =
//     SUBSETS ownedRelationship += OwnedSubsetting
subsets
    : subsetsToken ownedSubsetting
    ;

// References : Feature =
//     REFERENCES ownedRelationship += OwnedReferenceSubsetting
references
    : referencesToken ownedReferenceSubsetting
    ;

// Crosses : Feature =
//     CROSSES ownedRelationship += OwnedCrossSubsetting
crosses
    : crossesToken ownedCrossSubsetting
    ;

// Redefinitions : Feature =
//     Redefines ( ',' ownedRelationship += OwnedRedefinition )*
redefinitions
    : redefines ( COMMA ownedRedefinition )*
    ;

// Redefines : Feature =
//     REDEFINES ownedRelationship += OwnedRedefinition
redefines
    : redefinesToken ownedRedefinition
    ;

// 8.2.4.3.2 Feature Typing

// FeatureTyping =
//     ( 'specialization' Identification )?
//     'typing' typedFeature = [QualifiedName]
//     TYPED_BY GeneralType
//     RelationshipBody
featureTyping
    : ( SPECIALIZATION identification )?
      TYPING typedFeature=qualifiedName
      typedBy generalType
      relationshipBody
    ;

// OwnedFeatureTyping : FeatureTyping =
//     GeneralType
ownedFeatureTyping
    : generalType
    ;

// 8.2.4.3.3 Subsetting

// Subsetting =
//     ( 'specialization' Identification )?
//     'subset' SpecificType
//     SUBSETS GeneralType
//     RelationshipBody
subsetting
    : ( SPECIALIZATION identification )?
      SUBSET specificType
      subsetsToken generalType
      relationshipBody
    ;

// OwnedSubsetting : Subsetting =
//     GeneralType
ownedSubsetting
    : generalType
    ;

// OwnedReferenceSubsetting : ReferenceSubsetting =
//     GeneralType
ownedReferenceSubsetting
    : generalType
    ;

// OwnedCrossSubsetting : CrossSubsetting =
//     GeneralType
ownedCrossSubsetting
    : generalType
    ;

// 8.2.4.3.4 Redefinition

// Redefinition =
//     ( 'specialization' Identification )?
//     'redefinition' SpecificType
//     REDEFINES GeneralType
//     RelationshipBody
redefinition
    : ( SPECIALIZATION identification )?
      REDEFINITION specificType
      redefinesToken generalType
      relationshipBody
    ;

// OwnedRedefinition : Redefinition =
//     GeneralType
ownedRedefinition
    : generalType
    ;

// 8.2.4.3.5 Feature Chaining

// OwnedFeatureChain : Feature =
//     FeatureChain
ownedFeatureChain
    : featureChain
    ;

// FeatureChain : Feature =
//     ownedRelationship += OwnedFeatureChaining
//     ( '.' ownedRelationship += OwnedFeatureChaining )+
featureChain
    : ownedFeatureChaining
      ( DOT ownedFeatureChaining )+
    ;

// OwnedFeatureChaining : FeatureChaining =
//     chainingFeature = [QualifiedName]
ownedFeatureChaining
    : chainingFeature=qualifiedName
    ;

// 8.2.4.3.6 Feature Inverting

// FeatureInverting =
//     ( 'inverting' Identification? )?
//     'inverse'
//     ( featureInverted = [QualifiedName]
//       | featureInverted = OwnedFeatureChain
//         { ownedRelatedElement += featureInverted }
//     )
//     'of'
//     ( invertingFeature = [QualifiedName]
//       | ownedRelatedElement += OwnedFeatureChain
//         { ownedRelatedElement += invertingFeature }
//     )
//     RelationshipBody
featureInverting
    : ( INVERTING identification? )?
      INVERSE
      ( qualifiedName
      | ownedFeatureChain
      )
      OF
      ( qualifiedName
      | ownedFeatureChain
      )
      relationshipBody
    ;

// OwnedFeatureInverting : FeatureInverting =
//     invertingFeature = [QualifiedName]
//     | invertingFeature = OwnedFeatureChain
//       { ownedRelatedElement += invertingFeature }
ownedFeatureInverting
    : qualifiedName
    | ownedFeatureChain
    ;

// 8.2.4.3.7 Type Featuring

// TypeFeaturing =
//     'featuring' ( Identification 'of' )?
//     featureOfType = [QualifiedName]
//     'by' featuringType = [QualifiedName]
//     RelationshipBody
typeFeaturing
    : FEATURING ( identification OF )?
      featureOfType=qualifiedName
      BY featuringType=qualifiedName
      relationshipBody
    ;

// OwnedTypeFeaturing : TypeFeaturing =
//     featuringType = [QualifiedName]
ownedTypeFeaturing
    : featuringType=qualifiedName
    ;

// 8.2.5 Kernel Concrete Syntax
// 8.2.5.1 Data Types Concrete Syntax

// DataType =
//     TypePrefix 'datatype'
//     ClassifierDeclaration TypeBody
datatype
    : typePrefix DATATYPE
      classifierDeclaration typeBody
    ;

// 8.2.5.2 Classes Concrete Syntax

// Class =
//     TypePrefix 'class'
//     ClassifierDeclaration TypeBody
class
    : typePrefix CLASS
      classifierDeclaration typeBody
    ;

// 8.2.5.3 Structures Concrete Syntax

// Structure =
//     TypePrefix 'struct'
//     ClassifierDeclaration TypeBody
structure
    : typePrefix STRUCT
      classifierDeclaration typeBody
    ;

// 8.2.5.4 Associations Concrete Syntax

// Association =
//     TypePrefix 'assoc'
//     ClassifierDeclaration TypeBody
association
    : typePrefix ASSOC
      classifierDeclaration typeBody
    ;

// AssociationStructure =
//     TypePrefix 'assoc' 'struct'
//     ClassifierDeclaration TypeBody
associationStructure
    : typePrefix ASSOC STRUCT
      classifierDeclaration typeBody
    ;

// 8.2.5.5 Connectors Concrete Syntax
// 8.2.5.5.1 Connectors

// Connector =
//     FeaturePrefix 'connector'
//     ( FeatureDeclaration? ValuePart?
//       | ConnectorDeclaration
//     )
//     TypeBody
connector
    : featurePrefix CONNECTOR
      ( featureDeclaration? valuePart?
      | connectorDeclaration
      )
      typeBody
    ;

// ConnectorDeclaration : Connector =
//     BinaryConnectorDeclaration | NaryConnectorDeclaration
connectorDeclaration
    : binaryConnectorDeclaration
    | naryConnectorDeclaration
    ;

// BinaryConnectorDeclaration : Connector =
//     ( FeatureDeclaration? 'from' | isSufficient ?= 'all' 'from'? )?
//     ownedRelationship += ConnectorEndMember 'to'
//     ownedRelationship += ConnectorEndMember
binaryConnectorDeclaration
    : ( featureDeclaration? FROM | isSufficient=ALL FROM? )?
      connectorEndMember TO
      connectorEndMember
    ;

// NaryConnectorDeclaration : Connector =
//     FeatureDeclaration?
//     '(' ownedRelationship += ConnectorEndMember ','
//     ownedRelationship += ConnectorEndMember
//     ( ',' ownedRelationship += ConnectorEndMember )*
//     ')'
naryConnectorDeclaration
    : featureDeclaration?
      LPAREN connectorEndMember COMMA
      connectorEndMember
      ( COMMA connectorEndMember )*
      RPAREN
    ;

// ConnectorEndMember : EndFeatureMembership =
//     ownedRelatedElement += ConnectorEnd
connectorEndMember
    : connectorEnd
    ;

// ConnectorEnd : Feature =
//     ( ownedRelationship += OwnedCrossMultiplicityMember )?
//     ( declaredName = NAME REFERENCES )?
//     ownedRelationship += OwnedReferenceSubsetting
connectorEnd
    : ownedCrossMultiplicityMember?
      ( declaredName=NAME referencesToken )?
      ownedReferenceSubsetting
    ;

// OwnedCrossMultiplicityMember : OwningMembership =
//     ownedRelatedElement += OwnedCrossMultiplicity
ownedCrossMultiplicityMember
    : ownedCrossMultiplicity
    ;

// OwnedCrossMultiplicity : Feature =
//     ownedRelationship += OwnedMultiplicity
ownedCrossMultiplicity
    : ownedMultiplicity
    ;

// 8.2.5.5.2 Binding Connectors

// BindingConnector =
//     FeaturePrefix 'binding'
//     BindingConnectorDeclaration TypeBody
bindingConnector
    : featurePrefix BINDING
      bindingConnectorDeclaration typeBody
    ;

// BindingConnectorDeclaration : BindingConnector =
//     FeatureDeclaration
//     ( 'of' ownedRelationship += ConnectorEndMember
//       '=' ownedRelationship += ConnectorEndMember )?
//     | ( isSufficient ?= 'all' )?
//       ( 'of'? ownedRelationship += ConnectorEndMember
//         '=' ownedRelationship += ConnectorEndMember )?
bindingConnectorDeclaration
    : featureDeclaration
      ( OF connectorEndMember
        EQUALS connectorEndMember
      )?
    | ( isSufficient=ALL )?
      ( OF? connectorEndMember
        EQUALS connectorEndMember
      )?
    ;

// 8.2.5.5.3 Successions

// Succession =
//     FeaturePrefix 'succession'
//     SuccessionDeclaration TypeBody
succession
    : featurePrefix SUCCESSION
      successionDeclaration typeBody
    ;

// SuccessionDeclaration : Succession =
//     FeatureDeclaration
//     ( 'first' ownedRelationship += ConnectorEndMember
//       'then' ownedRelationship += ConnectorEndMember )?
//     | ( isSufficient ?= 'all' )?
//       ( 'first'? ownedRelationship += ConnectorEndMember
//         'then' ownedRelationship += ConnectorEndMember )?
successionDeclaration
    : featureDeclaration
      ( FIRST connectorEndMember
        THEN connectorEndMember
      )?
    | ( isSufficient=ALL )?
      ( FIRST? connectorEndMember
        THEN connectorEndMember
      )?
    ;

// 8.2.5.6 Behaviors Concrete Syntax
// 8.2.5.6.1 Behaviors

// Behavior =
//     TypePrefix 'behavior'
//     ClassifierDeclaration TypeBody
behavior
    : typePrefix BEHAVIOR
      classifierDeclaration typeBody
    ;

// 8.2.5.6.2 Steps

// Step =
//     FeaturePrefix
//     'step' FeatureDeclaration ValuePart?
//     TypeBody
step
    : featurePrefix
      STEP featureDeclaration? valuePart?
      typeBody
    ;

// 8.2.5.7 Functions Concrete Syntax
// 8.2.5.7.1 Functions

// Function =
//     TypePrefix 'function'
//     ClassifierDeclaration FunctionBody
function
    : typePrefix FUNCTION
      classifierDeclaration functionBody
    ;

// FunctionBody : Type =
//     ';' | '{' FunctionBodyPart '}'
functionBody
    : SEMICOLON
    | LBRACE functionBodyPart RBRACE
    ;

// FunctionBodyPart : Type =
//     ( TypeBodyElement
//       | ownedRelationship += ReturnFeatureMember
//     )*
//     ( ownedRelationship += ResultExpressionMember )?
functionBodyPart
    : ( typeBodyElement
      | returnFeatureMember
      )*
      resultExpressionMember?
    ;

// ReturnFeatureMember : ReturnParameterMembership =
//     MemberPrefix 'return'
//     ownedRelatedElement += FeatureElement
returnFeatureMember
    : memberPrefix RETURN
      featureElement
    ;

// ResultExpressionMember : ResultExpressionMembership =
//     MemberPrefix
//     ownedRelatedElement += OwnedExpression
resultExpressionMember
    : memberPrefix
      ownedExpression
    ;

// 8.2.5.7.2 Expressions

// Expression =
//     FeaturePrefix
//     'expr' FeatureDeclaration ValuePart?
//     FunctionBody
expression
    : featurePrefix
      EXPR featureDeclaration? valuePart?
      functionBody
    ;

// 8.2.5.7.3 Predicates

// Predicate =
//     TypePrefix 'predicate'
//     ClassifierDeclaration FunctionBody
predicate
    : typePrefix PREDICATE
      classifierDeclaration functionBody
    ;

// 8.2.5.7.4 Boolean Expressions and Invariants

// BooleanExpression =
//     FeaturePrefix
//     'bool' FeatureDeclaration ValuePart?
//     FunctionBody
booleanExpression
    : featurePrefix
      BOOL featureDeclaration? valuePart?
      functionBody
    ;

// Invariant =
//     FeaturePrefix
//     'inv' ( 'true' | isNegated ?= 'false' )?
//     FeatureDeclaration ValuePart?
//     FunctionBody
invariant
    : featurePrefix
      INV ( TRUE | isNegated=FALSE )?
      featureDeclaration? valuePart?
      functionBody
    ;

// 8.2.5.8 Expressions Concrete Syntax
// 8.2.5.8.1 Operator Expressions

// OwnedExpressionReferenceMember : FeatureMembership =
//     ownedRelationship += OwnedExpressionReference
ownedExpressionReferenceMember
    : ownedExpressionReference
    ;

// OwnedExpressionReference : FeatureReferenceExpression =
//     ownedRelationship += OwnedExpressionMember
ownedExpressionReference
    : ownedExpressionMember
    ;

// OwnedExpressionMember : FeatureMembership =
//     ownedFeatureMember = OwnedExpression
ownedExpressionMember
    : ownedExpression
    ;

// OwnedExpression : Expression =
//     ConditionalExpression
//     | ConditionalBinaryOperatorExpression
//     | BinaryOperatorExpression
//     | UnaryOperatorExpression
//     | ClassificationExpression
//     | MetaclassificationExpression
//     | ExtentExpression
//     | PrimaryExpression
// Refactored to use direct left recursion to eliminate mutual recursion.
// Binary operators split into precedence groups. In ANTLR 4 left-recursive rules,
// the FIRST listed alternative has the HIGHEST precedence (tightest binding).
ownedExpression
    : IF ownedExpression QUESTION ownedExpression ELSE ownedExpression emptyResultMember
    // LOCAL PATCH (sysml2-experiments): unary alternative moved above the
    // binary alternatives and its trailing emptyResultMember dropped so the
    // operand recursion is rightmost and inherits this (high) precedence.
    // Upstream, `-3 + 1` parsed as `-(3 + 1)`.
    | unaryOperator ownedExpression
    | ownedExpression exponentialOperator ownedExpression
    | ownedExpression multiplicativeOperator ownedExpression
    | ownedExpression additiveOperator ownedExpression
    | ownedExpression rangeOperator ownedExpression
    | ownedExpression relationalOperator ownedExpression
    | ownedExpression equalityOperator ownedExpression
    | ownedExpression bitwiseOperator ownedExpression
    | ownedExpression conditionalBinaryOperator ownedExpression
    | classificationTestOperator typeReferenceMember emptyResultMember
    | ownedExpression classificationTestOperator typeReferenceMember emptyResultMember
    | castOperator typeResultMember emptyResultMember
    | ownedExpression castOperator typeResultMember emptyResultMember
    | metadataAccessExpression metaclassificationTestOperator typeReferenceMember emptyResultMember
    | metadataAccessExpression metacastOperator typeResultMember emptyResultMember
    | ALL typeReferenceMember
    | primaryExpression
    ;

// ConditionalBinaryOperator =
//     '??' | 'or' | 'and' | 'implies'
conditionalBinaryOperator
    : DOUBLE_QUESTION
    | OR
    | AND
    | IMPLIES
    ;

// BinaryOperatorExpression : OperatorExpression =
//     ownedRelationship += ArgumentMember
//     operator = BinaryOperator
//     ownedRelationship += ArgumentMember
//     ownedRelationship += EmptyResultMember
binaryOperatorExpression
    : argumentMember
      operator=binaryOperator
      argumentMember
      emptyResultMember
    ;

// BinaryOperator — composite rule kept for binaryOperatorExpression backward compat
binaryOperator
    : equalityOperator
    | relationalOperator
    | additiveOperator
    | multiplicativeOperator
    | exponentialOperator
    | bitwiseOperator
    | rangeOperator
    ;

// Precedence-grouped operator sub-rules (used by ownedExpression for correct precedence)

equalityOperator
    : DOUBLE_EQUALS
    | EXCLAIM_EQUALS
    | TRIPLE_EQUALS
    | EXCLAIM_EQUALS_EQUALS
    ;

relationalOperator
    : LESS
    | GREATER
    | LESS_EQUALS
    | GREATER_EQUALS
    ;

additiveOperator
    : PLUS
    | MINUS
    ;

multiplicativeOperator
    : STAR
    | SLASH
    | PERCENT
    ;

exponentialOperator
    : CARET
    | DOUBLE_STAR
    ;

bitwiseOperator
    : PIPE
    | AMPERSAND
    | XOR
    ;

rangeOperator
    : DOUBLE_DOT
    ;

// UnaryOperatorExpression : OperatorExpression =
//     operator = UnaryOperator
//     ownedRelationship += ArgumentMember
//     ownedRelationship += EmptyResultMember
unaryOperatorExpression
    : operator=unaryOperator
      argumentMember
      emptyResultMember
    ;

// UnaryOperator =
//     '+' | '-' | '~' | 'not'
unaryOperator
    : PLUS
    | MINUS
    | TILDE
    | NOT
    ;

// ClassificationExpression : OperatorExpression =
//     ( ownedRelationship += ArgumentMember )?
//     ( operator = ClassificationTestOperator
//       ownedRelationship += TypeReferenceMember
//     | operator = CastOperator
//       ownedRelationship += TypeResultMember
//     )
//     ownedRelationship += EmptyResultMember
classificationExpression
    : argumentMember?
      ( classificationTestOperator
        typeReferenceMember
      | castOperator
        typeResultMember
      )
      emptyResultMember
    ;

// ClassificationTestOperator =
//     'istype' | 'hastype' | '@'
classificationTestOperator
    : ISTYPE
    | HASTYPE
    | AT
    ;

// CastOperator =
//     'as'
castOperator
    : AS
    ;

// MetaclassificationExpression : OperatorExpression =
//     ownedRelationship += MetadataArgumentMember
//     ( operator = MetaClassificationTestOperator
//       ownedRelationship += TypeReferenceMember
//     | operator = MetaCastOperator
//       ownedRelationship += TypeResultMember
//     )
//     ownedRelationship += EmptyResultMember
metaclassificationExpression
    : metadataArgumentMember
      ( metaclassificationTestOperator
        typeReferenceMember
      | metacastOperator
        typeResultMember
      )
      emptyResultMember
    ;

// ArgumentMember : ParameterMembership =
//     ownedMemberParameter = Argument
argumentMember
    : argument
    ;

// Argument : Feature =
//     ownedRelationship += ArgumentValue
argument
    : argumentValue
    ;

// ArgumentValue : FeatureValue =
//     value = OwnedExpression
argumentValue
    : ownedExpression
    ;

// ArgumentExpressionMember : FeatureMembership =
//     ownedRelatedElement += ArgumentExpression
argumentExpressionMember
    : argumentExpression
    ;

// ArgumentExpression : Feature =
//     ownedRelationship += ArgumentExpressionValue
argumentExpression
    : argumentExpressionValue
    ;

// ArgumentExpressionValue : FeatureValue =
//     value = OwnedExpressionReference
argumentExpressionValue
    : ownedExpressionReference
    ;

// MetadataArgumentMember : ParameterMembership =
//     ownedRelatedElement += MetadataArgument
metadataArgumentMember
    : metadataArgument
    ;

// MetadataArgument : Feature =
//     ownedRelationship += MetadataValue
metadataArgument
    : metadataValue
    ;

// MetadataValue : FeatureValue =
//     value = MetadataReference
metadataValue
    : metadataReference
    ;

// MetadataReference : MetadataAccessExpression =
//     ownedRelationship += ElementReferenceMember
metadataReference
    : elementReferenceMember
    ;

// MetaclassificationTestOperator =
//     '@@'
metaclassificationTestOperator
    : AT AT
    ;

// MetaCastOperator =
//     'meta'
metacastOperator
    : META
    ;

// ExtentExpression : OperatorExpression =
//     operator = 'all'
//     ownedRelationship += TypeReferenceMember
extentExpression
    : operator=ALL
      typeReferenceMember
    ;

// TypeReferenceMember : ParameterMembership =
//     ownedMemberFeature = TypeReference
typeReferenceMember
    : typeReference
    ;

// TypeResultMember : ResultParameterMembership =
//     ownedMemberFeature = TypeReference
typeResultMember
    : typeReference
    ;

// TypeReference : Feature =
//     ownedRelationship += ReferenceTyping
typeReference
    : referenceTyping
    ;

// ReferenceTyping : FeatureTyping =
//     type = [QualifiedName]
referenceTyping
    : qualifiedName
    ;

// EmptyResultMember : ReturnParameterMembership =
//     ownedRelatedElement += EmptyFeature
emptyResultMember
    : emptyFeature
    ;

// EmptyFeature : Feature =
//     { }
emptyFeature
    : // Empty rule
    ;

// 8.2.5.8.2 Primary Expressions

// PrimaryExpression : Expression =
//     FeatureChainExpression
//     | NonFeatureChainPrimaryExpression
// Refactored to use direct left recursion to eliminate mutual recursion
primaryExpression
    : primaryExpression LBRACKET sequenceExpressionListMember RBRACKET
    | primaryExpression HASH LPAREN sequenceExpressionListMember RPAREN
    | primaryExpression DOT featureChainMember
    | primaryExpression DOT bodyArgumentMember
    | primaryExpression DOT_QUESTION bodyArgumentMember
    | primaryExpression ARROW invocationTypeMember
      ( bodyArgumentMember | functionReferenceArgumentMember | argumentList )
      emptyResultMember
    | LPAREN sequenceExpressionList RPAREN
    | baseExpression
    ;

// PrimaryArgumentValue : FeatureValue =
//     value = PrimaryExpression
primaryArgumentValue
    : primaryExpression
    ;

// PrimaryArgument : Feature =
//     ownedRelationship += PrimaryArgumentValue
primaryArgument
    : primaryArgumentValue
    ;

// PrimaryArgumentMember : ParameterMembership =
//     ownedMemberParameter = PrimaryArgument
primaryArgumentMember
    : primaryArgument
    ;

// NonFeatureChainPrimaryExpression : Expression =
//     BracketExpression
//     | IndexExpression
//     | SequenceExpression
//     | SelectExpression
//     | CollectExpression
//     | FunctionOperationExpression
//     | BaseExpression
nonFeatureChainPrimaryExpression
    : bracketExpression
    | indexExpression
    | sequenceExpression
    | selectExpression
    | collectExpression
    | functionOperationExpression
    | baseExpression
    ;

// NonFeatureChainPrimaryArgumentValue : FeatureValue =
//     value = NonFeatureChainPrimaryExpression
nonFeatureChainPrimaryArgumentValue
    : nonFeatureChainPrimaryExpression
    ;

// NonFeatureChainPrimaryArgument : Feature =
//     ownedRelationship += NonFeatureChainPrimaryArgumentValue
nonFeatureChainPrimaryArgument
    : nonFeatureChainPrimaryArgumentValue
    ;

// NonFeatureChainPrimaryArgumentMember : ParameterMembership =
//     ownedMemberParameter = PrimaryArgument
nonFeatureChainPrimaryArgumentMember
    : primaryArgument
    ;

// BracketExpression : OperatorExpression =
//     ownedRelationship += PrimaryArgumentMember
//     operator = '['
//     ownedRelationship += SequenceExpressionListMember ']'
bracketExpression
    : primaryArgumentMember
      operator=LBRACKET
      sequenceExpressionListMember RBRACKET
    ;

// IndexExpression =
//     ownedRelationship += PrimaryArgumentMember '#'
//     '(' ownedRelationship += SequenceExpressionListMember ')'
indexExpression
    : primaryArgumentMember HASH
      LPAREN sequenceExpressionListMember RPAREN
    ;

// SequenceExpression : Expression =
//     '(' SequenceExpressionList ')'
sequenceExpression
    : LPAREN sequenceExpressionList RPAREN
    ;

// SequenceExpressionList : Expression =
//     OwnedExpression ','? | SequenceOperatorExpression
sequenceExpressionList
    : ownedExpression COMMA?
    | sequenceOperatorExpression
    ;

// SequenceOperatorExpression : OperatorExpression =
//     ownedRelationship += OwnedExpressionMember
//     operator = ','
//     ownedRelationship += SequenceExpressionListMember
sequenceOperatorExpression
    : ownedExpressionMember
      operator=COMMA
      sequenceExpressionListMember
    ;

// SequenceExpressionListMember : FeatureMembership =
//     ownedMemberFeature = SequenceExpressionList
sequenceExpressionListMember
    : sequenceExpressionList
    ;

// FeatureChainExpression =
//     ownedRelationship += NonFeatureChainPrimaryArgumentMember '.'
//     ownedRelationship += FeatureChainMember
featureChainExpression
    : nonFeatureChainPrimaryArgumentMember DOT
      featureChainMember
    ;

// CollectExpression =
//     ownedRelationship += PrimaryArgumentMember '.'
//     ownedRelationship += BodyArgumentMember
collectExpression
    : primaryArgumentMember DOT
      bodyArgumentMember
    ;

// SelectExpression =
//     ownedRelationship += PrimaryArgumentMember '.?'
//     ownedRelationship += BodyArgumentMember
selectExpression
    : primaryArgumentMember DOT_QUESTION
      bodyArgumentMember
    ;

// FunctionOperationExpression : InvocationExpression =
//     ownedRelationship += PrimaryArgumentMember '->'
//     ownedRelationship += InvocationTypeMember
//     ( ownedRelationship += BodyArgumentMember
//       | ownedRelationship += FunctionReferenceArgumentMember
//       | ArgumentList )
//     ownedRelationship += EmptyResultMember
functionOperationExpression
    : primaryArgumentMember ARROW
      invocationTypeMember
      ( bodyArgumentMember
      | functionReferenceArgumentMember
      | argumentList
      )
      emptyResultMember
    ;

// BodyArgumentMember : ParameterMembership =
//     ownedMemberParameter = BodyArgument
bodyArgumentMember
    : bodyArgument
    ;

// BodyArgument : Feature =
//     ownedRelationship += BodyArgumentValue
bodyArgument
    : bodyArgumentValue
    ;

// BodyArgumentValue : FeatureValue =
//     value = BodyExpression
bodyArgumentValue
    : bodyExpression
    ;

// FunctionReferenceArgumentMember : ParameterMembership =
//     ownedMemberParameter = FunctionReferenceArgument
functionReferenceArgumentMember
    : functionReferenceArgument
    ;

// FunctionReferenceArgument : Feature =
//     ownedRelationship += FunctionReferenceArgumentValue
functionReferenceArgument
    : functionReferenceArgumentValue
    ;

// FunctionReferenceArgumentValue : FeatureValue =
//     value = FunctionReferenceExpression
functionReferenceArgumentValue
    : functionReferenceExpression
    ;

// FunctionReferenceExpression : FeatureReferenceExpression =
//     ownedRelationship += FunctionReferenceMember
functionReferenceExpression
    : functionReferenceMember
    ;

// FunctionReferenceMember : FeatureMembership =
//     ownedMemberFeature = FunctionReference
functionReferenceMember
    : functionReference
    ;

// FunctionReference : Expression =
//     ownedRelationship += ReferenceTyping
functionReference
    : referenceTyping
    ;

// FeatureChainMember : Membership =
//     FeatureReferenceMember
//     | OwnedFeatureChainMember
featureChainMember
    : featureReferenceMember
    | ownedFeatureChainMember
    ;

// InvocationTypeMember : FeatureMembership =
//     ownedMemberFeature = InvocationType
invocationTypeMember
    : invocationType
    ;

// InvocationType : Type =
//     ownedRelationship += OwnedFeatureTyping
invocationType
    : ownedFeatureTyping
    ;

// 8.2.5.8.3 Base Expressions

// BaseExpression : Expression =
//     NullExpression
//     | LiteralExpression
//     | FeatureReferenceExpression
//     | MetadataAccessExpression
//     | InvocationExpression
//     | ConstructorExpression
//     | BodyExpression
baseExpression
    : nullExpression
    | literalExpression
    | featureReferenceExpression
    | metadataAccessExpression
    | invocationExpression
    | constructorExpression
    | bodyExpression
    ;

// NullExpression : NullExpression =
//     'null' | '(' ')'
nullExpression
    : NULL
    | LPAREN RPAREN
    ;

// FeatureReferenceExpression : FeatureReferenceExpression =
//     ownedRelationship += FeatureReferenceMember
//     ownedRelationship += EmptyResultMember
featureReferenceExpression
    : featureReferenceMember
      emptyResultMember
    ;

// FeatureReferenceMember : Membership =
//     memberElement = FeatureReference
featureReferenceMember
    : featureReference
    ;

// FeatureReference : Feature =
//     [QualifiedName]
featureReference
    : qualifiedName
    ;

// MetadataAccessExpression =
//     ownedRelationship += ElementReferenceMember '.' 'metadata'
metadataAccessExpression
    : elementReferenceMember DOT METADATA
    ;

// ElementReferenceMember : Membership =
//     memberElement = [QualifiedName]
elementReferenceMember
    : qualifiedName
    ;

// InvocationExpression : InvocationExpression =
//     ownedRelationship += InstantiatedTypeMember
//     ArgumentList
//     ownedRelationship += EmptyResultMember
invocationExpression
    : instantiatedTypeMember
      argumentList
      emptyResultMember
    ;

// ConstructorExpression =
//     'new' ownedRelationship += InstantiatedTypeMember
//     ownedRelationship += ConstructorResultMember
constructorExpression
    : NEW instantiatedTypeMember
      constructorResultMember
    ;

// ConstructorResultMember : ReturnParameterMembership =
//     ownedRelatedElement += ConstructorResult
constructorResultMember
    : constructorResult
    ;

// ConstructorResult : Feature =
//     ArgumentList
constructorResult
    : argumentList
    ;

// InstantiatedTypeMember : Membership =
//     memberElement = InstantiatedTypeReference
//     | OwnedFeatureChainMember
instantiatedTypeMember
    : instantiatedTypeReference
    | ownedFeatureChainMember
    ;

// InstantiatedTypeReference : Type =
//     [QualifiedName]
instantiatedTypeReference
    : qualifiedName
    ;

// OwnedFeatureChainMember : Membership =
//     ownedRelatedElement = OwnedFeatureChain
ownedFeatureChainMember
    : ownedFeatureChain
    ;

// ArgumentList : Feature =
//     '(' ( PositionalArgumentList | NamedArgumentList )? ')'
argumentList
    : LPAREN ( positionalArgumentList | namedArgumentList )? RPAREN
    ;

// PositionalArgumentList : Feature =
//     ownedRelationship += ArgumentMember
//     ( ',' ownedRelationship += ArgumentMember )*
positionalArgumentList
    : argumentMember
      ( COMMA argumentMember )*
    ;

// NamedArgumentList : Feature =
//     ownedRelationship += NamedArgumentMember
//     ( ',' ownedRelationship += NamedArgumentMember )*
namedArgumentList
    : namedArgumentMember
      ( COMMA namedArgumentMember )*
    ;

// NamedArgumentMember : FeatureMembership =
//     ownedMemberFeature = NamedArgument
namedArgumentMember
    : namedArgument
    ;

// NamedArgument : Feature =
//     ownedRelationship += ParameterRedefinition '='
//     ownedRelationship += ArgumentValue
namedArgument
    : parameterRedefinition EQUALS
      argumentValue
    ;

// ParameterRedefinition : Redefinition =
//     redefinedFeature = [QualifiedName]
parameterRedefinition
    : qualifiedName
    ;

// BodyExpression : FeatureReferenceExpression =
//     ownedRelationship += ExpressionBodyMember
bodyExpression
    : expressionBodyMember
    ;

// ExpressionBodyMember : FeatureMembership =
//     ownedMemberFeature = ExpressionBody
expressionBodyMember
    : expressionBody
    ;

// ExpressionBody : Expression =
//     '{' FunctionBodyPart '}'
expressionBody
    : LBRACE functionBodyPart RBRACE
    ;

// 8.2.5.8.4 Literal Expressions

// LiteralExpression =
//     LiteralBoolean
//     | LiteralString
//     | LiteralInteger
//     | LiteralReal
//     | LiteralInfinity
literalExpression
    : literalBoolean
    | literalString
    | literalInteger
    | literalReal
    | literalInfinity
    ;

// LiteralBoolean =
//     value = BooleanValue
literalBoolean
    : value=booleanValue
    ;

// BooleanValue : Boolean =
//     'true' | 'false'
booleanValue
    : TRUE
    | FALSE
    ;

// LiteralString =
//     value = STRING_VALUE
literalString
    : value=STRING_VALUE
    ;

// LiteralInteger =
//     value = DECIMAL_VALUE
literalInteger
    : value=DECIMAL_VALUE
    ;

// LiteralReal =
//     value = RealValue
literalReal
    : value=realValue
    ;

// RealValue : Real =
//     DECIMAL_VALUE? '.' ( DECIMAL_VALUE | EXPONENTIAL_VALUE )
//     | EXPONENTIAL_VALUE
realValue
    : DECIMAL_VALUE? DOT ( DECIMAL_VALUE | EXPONENTIAL_VALUE )
    | EXPONENTIAL_VALUE
    ;

// LiteralInfinity =
//     '*'
literalInfinity
    : STAR
    ;

// 8.2.5.9 Interactions Concrete Syntax
// 8.2.5.9.1 Interactions

// Interaction =
//     TypePrefix 'interaction'
//     ClassifierDeclaration TypeBody
interaction
    : typePrefix INTERACTION
      classifierDeclaration typeBody
    ;

// 8.2.5.9.2 Flows

// Flow =
//     FeaturePrefix 'flow'
//     ItemFlowDeclaration TypeBody
flow
    : featurePrefix FLOW
      itemFlowDeclaration typeBody
    ;

// SuccessionFlow =
//     FeaturePrefix 'succession' 'flow'
//     ItemFlowDeclaration TypeBody
successionFlow
    : featurePrefix SUCCESSION FLOW
      itemFlowDeclaration typeBody
    ;

// FlowDeclaration : Flow =
//     FeatureDeclaration ValuePart?
//     ( 'of' ownedRelationship += PayloadFeatureMember )?
//     ( 'from' ownedRelationship += FlowEndMember
//       'to' ownedRelationship += FlowEndMember )?
//     | ( isSufficient ?= 'all' )?
//       ownedRelationship += FlowEndMember 'to'
//       ownedRelationship += FlowEndMember
itemFlowDeclaration
    : featureDeclaration valuePart?
      ( OF payloadFeatureMember )?
      ( FROM flowEndMember
        TO flowEndMember
      )?
    | ( isSufficient=ALL )?
      flowEndMember TO
      flowEndMember
    ;

// PayloadFeatureMember : FeatureMembership =
//     ownedRelatedElement = PayloadFeature
payloadFeatureMember
    : payloadFeature
    ;

// PayloadFeature =
//     Identification PayloadFeatureSpecializationPart ValuePart?
//     | Identification ValuePart
//     | ( ownedRelationship += OwnedFeatureTyping
//         ( ownedRelationship += OwnedMultiplicity )?
//       | ownedRelationship += OwnedMultiplicity
//         ( ownedRelationship += OwnedFeatureTyping )?
//       )
payloadFeature
    : identification payloadFeatureSpecializationPart valuePart?
    | identification valuePart
    | ( ownedFeatureTyping ownedMultiplicity?
      | ownedMultiplicity ownedFeatureTyping?
      )
    ;

// PayloadFeatureSpecializationPart : Feature =
//     FeatureSpecialization+ MultiplicityPart?
//     FeatureSpecialization*
//     | MultiplicityPart FeatureSpecialization+
payloadFeatureSpecializationPart
    : featureSpecialization+ multiplicityPart?
      featureSpecialization*
    | multiplicityPart featureSpecialization+
    ;

// FlowEndMember : EndFeatureMembership =
//     ownedRelatedElement += FlowEnd
flowEndMember
    : flowEnd
    ;

// FlowEnd =
//     ( ownedRelationship += OwnedReferenceSubsetting '.' )?
//     ownedRelationship += FlowFeatureMember
flowEnd
    : ( ownedReferenceSubsetting DOT )?
      flowFeatureMember
    ;

// FlowFeatureMember : FeatureMembership =
//     ownedRelatedElement += FlowFeature
flowFeatureMember
    : flowFeature
    ;

// FlowFeature : Feature =
//     ownedRelationship += FlowFeatureRedefinition
flowFeature
    : flowFeatureRedefinition
    ;

// FlowFeatureRedefinition : Redefinition =
//     redefinedFeature = [QualifiedName]
flowFeatureRedefinition
    : qualifiedName
    ;

// 8.2.5.10 Feature Values Concrete Syntax

// ValuePart : Feature =
//     ownedRelationship += FeatureValue
valuePart
    : featureValue
    ;

// FeatureValue =
//     ( '='
//     | isInitial ?= ':='
//     | isDefault ?= 'default' ( '=' | isInitial ?= ':=' )?
//     )
//     ownedRelatedElement += OwnedExpression
featureValue
    : ( EQUALS
      | isInitial=COLON_EQUALS
      | isDefault=DEFAULT ( EQUALS | isInitial=COLON_EQUALS )?
      )
      ownedExpression
    ;

// 8.2.5.11 Multiplicities Concrete Syntax

// Multiplicity =
//     MultiplicitySubset | MultiplicityRange
multiplicity
    : multiplicitySubset
    | multiplicityRange
    ;

// MultiplicitySubset : Multiplicity =
//     'multiplicity' Identification Subsets
//     TypeBody
multiplicitySubset
    : MULTIPLICITY identification subsets
      typeBody
    ;

// MultiplicityRange =
//     'multiplicity' Identification MultiplicityBounds
//     TypeBody
multiplicityRange
    : MULTIPLICITY identification multiplicityBounds
      typeBody
    ;

// OwnedMultiplicity : OwningMembership =
//     ownedRelatedElement += OwnedMultiplicityRange
ownedMultiplicity
    : ownedMultiplicityRange
    ;

// OwnedMultiplicityRange : MultiplicityRange =
//     MultiplicityBounds
ownedMultiplicityRange
    : multiplicityBounds
    ;

// MultiplicityBounds : MultiplicityRange =
//     '[' ( ownedRelationship += MultiplicityExpressionMember '..' )?
//     ownedRelationship += MultiplicityExpressionMember ']'
multiplicityBounds
    : LBRACKET ( multiplicityExpressionMember DOUBLE_DOT )?
      multiplicityExpressionMember RBRACKET
    ;

// MultiplicityExpressionMember : OwningMembership =
//     ownedRelatedElement += ( LiteralExpression | FeatureReferenceExpression )
multiplicityExpressionMember
    : literalExpression
    | featureReferenceExpression
    ;

// 8.2.5.12 Metadata Concrete Syntax

// Metaclass =
//     TypePrefix 'metaclass'
//     ClassifierDeclaration TypeBody
metaclass
    : typePrefix METACLASS
      classifierDeclaration typeBody
    ;

// PrefixMetadataAnnotation : Annotation =
//     '#' ownedRelatedElement += PrefixMetadataFeature
prefixMetadataAnnotation
    : HASH prefixMetadataFeature
    ;

// PrefixMetadataMember : OwningMembership =
//     '#' ownedRelatedElement += PrefixMetadataFeature
prefixMetadataMember
    : HASH prefixMetadataFeature
    ;

// PrefixMetadataFeature : MetadataFeature =
//     ownedRelationship += OwnedFeatureTyping
prefixMetadataFeature
    : ownedFeatureTyping
    ;

// MetadataFeature =
//     ( ownedRelationship += PrefixMetadataMember )*
//     ( '@' | 'metadata' )
//     MetadataFeatureDeclaration
//     ( 'about' ownedRelationship += Annotation
//       ( ',' ownedRelationship += Annotation )*
//     )?
//     MetadataBody
metadataFeature
    : prefixMetadataMember*
      ( AT | METADATA )
      metadataFeatureDeclaration
      ( ABOUT annotation
        ( COMMA annotation )*
      )?
      metadataBody
    ;

// MetadataFeatureDeclaration : MetadataFeature =
//     ( Identification ( ':' | 'typed' 'by' ) )?
//     ownedRelationship += OwnedFeatureTyping
metadataFeatureDeclaration
    : ( identification ( COLON | TYPED BY ) )?
      ownedFeatureTyping
    ;

// MetadataBody : Feature =
//     ';' | '{' ( ownedRelationship += MetadataBodyElement )* '}'
metadataBody
    : SEMICOLON
    | LBRACE metadataBodyElement* RBRACE
    ;

// MetadataBodyElement : Membership =
//     NonFeatureMember
//     | MetadataBodyFeatureMember
//     | AliasMember
//     | Import
metadataBodyElement
    : nonFeatureMember
    | metadataBodyFeatureMember
    | aliasMember
    | import_
    ;

// MetadataBodyFeatureMember : FeatureMembership =
//     ownedMemberFeature = MetadataBodyFeature
metadataBodyFeatureMember
    : metadataBodyFeature
    ;

// MetadataBodyFeature : Feature =
//     'feature'? ( ':>>' | 'redefines')? ownedRelationship += OwnedRedefinition
//     FeatureSpecializationPart? ValuePart?
//     MetadataBody
metadataBodyFeature
    : FEATURE? ( COLON_GT_GT | REDEFINES )? ownedRedefinition
      featureSpecializationPart? valuePart?
      metadataBody
    ;

// 8.2.5.13 Packages Concrete Syntax

// Package =
//     ( ownedRelationship += PrefixMetadataMember )*
//     PackageDeclaration PackageBody
package
    : prefixMetadataMember*
      packageDeclaration packageBody
    ;

// LibraryPackage =
//     ( isStandard ?= 'standard' ) 'library'
//     ( ownedRelationship += PrefixMetadataMember )*
//     PackageDeclaration PackageBody
libraryPackage
    : isStandard=STANDARD LIBRARY
      prefixMetadataMember*
      packageDeclaration packageBody
    ;

// PackageDeclaration : Package =
//     'package' Identification
packageDeclaration
    : PACKAGE identification
    ;

// PackageBody : Package =
//     ';'
//     | '{' ( NamespaceBodyElement
//         | ownedRelationship += ElementFilterMember
//       )*
//       '}'
packageBody
    : SEMICOLON
    | LBRACE ( namespaceBodyElement
             | elementFilterMember
             )*
      RBRACE
    ;

// ElementFilterMember : ElementFilterMembership =
//     MemberPrefix
//     'filter' condition = OwnedExpression ';'
elementFilterMember
    : memberPrefix
      FILTER condition=ownedExpression SEMICOLON
    ;

// Views Extension (non-normative)
// Collapsed from SysML into KerML for View, Rendering, Viewpoint, Expose.

// View = TypePrefix 'view' ClassifierDeclaration ViewBody
view
    : typePrefix VIEW
      classifierDeclaration viewBody
    ;

viewBody
    : SEMICOLON
    | LBRACE viewBodyElement* RBRACE
    ;

viewBodyElement
    : typeBodyElement
    | expose
    | viewRenderingMember
    ;

// Expose = 'expose' ('all')? ImportDeclaration RelationshipBody
expose
    : EXPOSE ( isImportAll=ALL )?
      importDeclaration relationshipBody
    ;

// ViewRenderingMember = MemberPrefix 'render' QualifiedName TypeBody
viewRenderingMember
    : memberPrefix RENDER
      qualifiedName typeBody
    ;

// Rendering = TypePrefix 'rendering' ClassifierDeclaration TypeBody
rendering
    : typePrefix RENDERING
      classifierDeclaration typeBody
    ;

// Viewpoint = TypePrefix 'viewpoint' ClassifierDeclaration FunctionBody
viewpoint
    : typePrefix VIEWPOINT
      classifierDeclaration functionBody
    ;

// ===== Lexer Rules =====

// 8.2.2.6 Reserved Words
// Keywords that have the lexical structure of basic names but cannot be used as names
// Note: These must be defined before BASIC_NAME to have higher priority in lexer matching

ABOUT : 'about' ;
ABSTRACT : 'abstract' ;
ALIAS : 'alias' ;
ALL : 'all' ;
AND : 'and' ;
AS : 'as' ;
ASSOC : 'assoc' ;
BEHAVIOR : 'behavior' ;
BINDING : 'binding' ;
BOOL : 'bool' ;
BY : 'by' ;
CHAINS : 'chains' ;
CLASS : 'class' ;
CLASSIFIER : 'classifier' ;
COMMENT : 'comment' ;
COMPOSITE : 'composite' ;
CONJUGATE : 'conjugate' ;
CONJUGATES : 'conjugates' ;
CONJUGATION : 'conjugation' ;
CONNECTOR : 'connector' ;
CONST : 'const' ;
CROSSES : 'crosses' ;
DATATYPE : 'datatype' ;
DEFAULT : 'default' ;
DEPENDENCY : 'dependency' ;
DERIVED : 'derived' ;
DIFFERENCES : 'differences' ;
DISJOINING : 'disjoining' ;
DISJOINT : 'disjoint' ;
DOC : 'doc' ;
ELSE : 'else' ;
END : 'end' ;
EXPOSE : 'expose' ;
EXPR : 'expr' ;
FALSE : 'false' ;
FEATURE : 'feature' ;
FEATURED : 'featured' ;
FEATURING : 'featuring' ;
FILTER : 'filter' ;
FIRST : 'first' ;
FLOW : 'flow' ;
FOR : 'for' ;
FROM : 'from' ;
FUNCTION : 'function' ;
HASTYPE : 'hastype' ;
IF : 'if' ;
IMPLIES : 'implies' ;
IMPORT : 'import' ;
IN : 'in' ;
INOUT : 'inout' ;
INTERACTION : 'interaction' ;
INTERSECTS : 'intersects' ;
INV : 'inv' ;
INVERSE : 'inverse' ;
INVERTING : 'inverting' ;
ISTYPE : 'istype' ;
LANGUAGE : 'language' ;
LIBRARY : 'library' ;
LOCALE : 'locale' ;
MEMBER : 'member' ;
META : 'meta' ;
METACLASS : 'metaclass' ;
METADATA : 'metadata' ;
MULTIPLICITY : 'multiplicity' ;
NAMESPACE : 'namespace' ;
NEW : 'new' ;
NONUNIQUE : 'nonunique' ;
NOT : 'not' ;
NULL : 'null' ;
OF : 'of' ;
OR : 'or' ;
ORDERED : 'ordered' ;
OUT : 'out' ;
PACKAGE : 'package' ;
PORTION : 'portion' ;
PREDICATE : 'predicate' ;
PRIVATE : 'private' ;
PROTECTED : 'protected' ;
PUBLIC : 'public' ;
REDEFINES : 'redefines' ;
REDEFINITION : 'redefinition' ;
REFERENCES : 'references' ;
RENDER : 'render' ;
RENDERING : 'rendering' ;
REP : 'rep' ;
RETURN : 'return' ;
SPECIALIZATION : 'specialization' ;
SPECIALIZES : 'specializes' ;
STANDARD : 'standard' ;
STEP : 'step' ;
STRUCT : 'struct' ;
SUBCLASSIFIER : 'subclassifier' ;
SUBSET : 'subset' ;
SUBSETS : 'subsets' ;
SUBTYPE : 'subtype' ;
SUCCESSION : 'succession' ;
THEN : 'then' ;
TO : 'to' ;
TRUE : 'true' ;
TYPE : 'type' ;
TYPED : 'typed' ;
TYPING : 'typing' ;
UNIONS : 'unions' ;
VAR : 'var' ;
VIEW : 'view' ;
VIEWPOINT : 'viewpoint' ;
XOR : 'xor' ;

// 8.2.2.7 Symbols
// Non-alphanumeric tokens, ordered by length (longest first) for proper matching
// Note: Multi-character symbols must be matched before their single-character components

// Multi-character symbols (longest first)
DOUBLE_COLON_GT : '::>' ;
COLON_GT_GT : ':>>' ;
TRIPLE_EQUALS : '===' ;
EXCLAIM_EQUALS_EQUALS : '!==' ;
DOUBLE_STAR : '**' ;
DOUBLE_EQUALS : '==' ;
EXCLAIM_EQUALS : '!=' ;
LESS_EQUALS : '<=' ;
GREATER_EQUALS : '>=' ;
COLON_EQUALS : ':=' ;
DOUBLE_COLON : '::' ;
COLON_GT : ':>' ;
ARROW : '->' ;
DOUBLE_DOT : '..' ;
EQUALS_GT : '=>' ;
DOUBLE_QUESTION : '??' ;
DOT_QUESTION : '.?' ;

// Single-character symbols
LPAREN : '(' ;
RPAREN : ')' ;
LBRACE : '{' ;
RBRACE : '}' ;
LBRACKET : '[' ;
RBRACKET : ']' ;
SEMICOLON : ';' ;
COMMA : ',' ;
TILDE : '~' ;
AT : '@' ;
HASH : '#' ;
PERCENT : '%' ;
AMPERSAND : '&' ;
CARET : '^' ;
PIPE : '|' ;
STAR : '*' ;
PLUS : '+' ;
MINUS : '-' ;
SLASH : '/' ;
DOLLAR : '$' ;
DOT : '.' ;
COLON : ':' ;
LESS : '<' ;
EQUALS : '=' ;
GREATER : '>' ;
QUESTION : '?' ;

// Note: Special lexical terminals like TYPED_BY (': | typed by') are handled
// in parser rules, not lexer rules, because they involve keyword sequences


// 8.2.2.1 Line Terminators (defined first as it's referenced by other rules)
// LINE_TERMINATOR: implementation defined character sequence
// Order matters: match CRLF before CR or LF alone
// Sent to HIDDEN channel to be ignored during parsing
LINE_TERMINATOR
    : ( '\r\n'  // Windows-style CRLF (must be first)
      | '\r'    // Classic Mac-style CR
      | '\n'    // Unix-style LF
      ) -> channel(HIDDEN)
    ;

// 8.2.2.2 Notes and Comments

// SINGLE_LINE_NOTE: '//' LINE_TEXT
// Terminated by LINE_TERMINATOR (see note 3 in 8.2.2.1)
// LOCAL PATCH (sysml2-experiments): must not start with '*', otherwise the
// longest-match rule swallows a one-line `//* ... */ trailing` note as a
// single-line note, eating the text after the '*/'.
SINGLE_LINE_NOTE
    : '//' ( ~[*\r\n] ~[\r\n]* )? -> channel(HIDDEN)
    ;

// MULTILINE_NOTE: '//*' COMMENT_TEXT '*/'
MULTILINE_NOTE
    : '//*' .*? '*/' -> channel(HIDDEN)
    ;

// REGULAR_COMMENT: '/*' COMMENT_TEXT '*/'
// Note: NOT sent to hidden channel because documentation bodies use this syntax
REGULAR_COMMENT
    : '/*' .*? '*/'
    ;

// COMMENT_TEXT: ( COMMENT_LINE_TEXT | LINE_TERMINATOR )*
// COMMENT_LINE_TEXT: LINE_TEXT excluding the sequence '*/'
// These are handled inline by the .*? non-greedy match in MULTILINE_NOTE and REGULAR_COMMENT

// 8.2.2.3 Names
// Notes:
// 1. The single_quote character is '. Characters within quotes form the name (quotes excluded).
// 2. ESCAPE_SEQUENCE: backslash sequences representing single characters (see Table 4)
//    Allowed escapes: \b \f \n \r \t \' \\ and newline continuation
// 3. BASIC_NAME must be defined AFTER reserved keywords (8.2.2.6) to ensure proper lexer priority

// UNRESTRICTED_NAME: single_quote ( NAME_CHARACTER | ESCAPE_SEQUENCE )* single_quote
// NOTE: Must be a fragment so that quoted names produce NAME tokens, not UNRESTRICTED_NAME tokens.
// Without fragment, 'locale', '+', '==' etc. are emitted as their own token type and rejected by parser rules.
fragment UNRESTRICTED_NAME
    : '\'' ( NAME_CHARACTER | ESCAPE_SEQUENCE )* '\''
    ;

// Fragments for name components

// BASIC_INITIAL_CHARACTER: ALPHABETIC_CHARACTER | '_'
fragment BASIC_INITIAL_CHARACTER
    : ALPHABETIC_CHARACTER
    | '_'
    ;

// BASIC_NAME_CHARACTER: BASIC_INITIAL_CHARACTER | DECIMAL_DIGIT
fragment BASIC_NAME_CHARACTER
    : BASIC_INITIAL_CHARACTER
    | DECIMAL_DIGIT
    ;

// ALPHABETIC_CHARACTER: any character 'a' through 'z' or 'A' through 'Z'
fragment ALPHABETIC_CHARACTER
    : [a-zA-Z]
    ;

// DECIMAL_DIGIT: any character '0' through '9'
fragment DECIMAL_DIGIT
    : [0-9]
    ;

// NAME_CHARACTER: any printable character other than backslash or single_quote
fragment NAME_CHARACTER
    : ~['\\]  // Any character except single quote and backslash
    ;

// ESCAPE_SEQUENCE: two-character sequences starting with backslash (see Table 4)
// Allowed: \' \" \b \f \t \n \\ and line continuation
fragment ESCAPE_SEQUENCE
    : '\\\''  // single quote
    | '\\"'   // double quote
    | '\\b'   // backspace
    | '\\f'   // form feed
    | '\\t'   // tab
    | '\\n'   // line terminator (newline)
    | '\\\\'  // backslash
    | '\\' LINE_TERMINATOR  // line continuation (resolves to actual line terminator)
    ;

// 8.2.2.4 Numeric Values
// Notes:
// 1. DECIMAL_VALUE may specify a natural literal or be part of a real literal (see 8.2.5.8.4)
//    Sign is not included - negation is handled as an operator in Expression syntax
// 2. EXPONENTIAL_VALUE may be used in real literals (see 8.2.5.8.4)
//    Decimal point and fractional part are handled in real literal syntax, not here

// DECIMAL_VALUE: DECIMAL_DIGIT+
DECIMAL_VALUE
    : DECIMAL_DIGIT+
    ;

// EXPONENTIAL_VALUE: DECIMAL_VALUE ('e' | 'E') ('+' | '-')? DECIMAL_VALUE
EXPONENTIAL_VALUE
    : DECIMAL_VALUE [eE] [+\-]? DECIMAL_VALUE
    ;

// 8.2.2.5 String Value

// STRING_VALUE: '"' ( STRING_CHARACTER | ESCAPE_SEQUENCE )* '"'
STRING_VALUE
    : '"' ( STRING_CHARACTER | ESCAPE_SEQUENCE )* '"'
    ;

// STRING_CHARACTER: any printable character other than backslash or '"'
fragment STRING_CHARACTER
    : ~["\\]  // Any character except double quote and backslash
    ;



// 8.2.2.3 Names (continued)
// BASIC_NAME is defined here, AFTER reserved keywords, to give keywords priority
// NOTE: BASIC_NAME must be a fragment so that only NAME is emitted as a token

// BASIC_NAME: BASIC_INITIAL_CHARACTER BASIC_NAME_CHARACTER*
fragment BASIC_NAME
    : BASIC_INITIAL_CHARACTER BASIC_NAME_CHARACTER*
    ;

// NAME: BASIC_NAME | UNRESTRICTED_NAME
NAME
    : BASIC_NAME
    | UNRESTRICTED_NAME
    ;

// 8.2.2.1 White Space (defined last to avoid interfering with other token matching)
// Notes:
// 1. LINE_TERMINATOR defined at start of lexer rules (line 11)
// 2. LINE_TEXT refers to characters in a text line that are not part of LINE_TERMINATOR
// 3. WHITE_SPACE separates tokens and is otherwise ignored, EXCEPT line terminators
//    are used to mark the end of single-line notes (see 8.2.2.2)

// WHITE_SPACE: space | tab | form_feed
// Non-line-terminator white space sent to hidden channel for potential future use
WS
    : [ \t\f]+ -> channel(HIDDEN)
    ;

// LINE_TEXT is not explicitly defined as a lexer rule since it represents
// character sequences excluding LINE_TERMINATORs, which is context-dependent
