grammar SysML;

// ===== Parser Rules =====

// SysML grammar - to be built incrementally.
// The expression sub-grammar (`ownedExpression` and operator rules near the end
// of this file) is duplicated from KerML.g4 verbatim: the SysML spec references
// `OwnedExpression` without defining it, so its definition is inherited from
// KerML (see KerML 7.4.9). Keep those rules in sync with KerML.g4.

// Special lexical terminals (keyword/symbol equivalents)
// These allow either symbolic or keyword forms for convenience

// DEFINED_BY = ':' | 'defined' 'by'
definedByToken
    : COLON
    | DEFINED BY
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

// QualifiedName =
//     ( '$' '::' )? ( NAME '::' )* NAME
qualifiedName
    : ( DOLLAR DOUBLE_COLON )?
      ( NAME DOUBLE_COLON )*
      NAME
    ;

// 8.2.2.2 Elements and Relationships Textual Notation

// Identification : Element =
//     ( '<' declaredShortName = NAME '>' )?
//     ( declaredName = NAME )?
identification
    : ( LESS declaredShortName=NAME GREATER )?
      ( declaredName=NAME )?
    ;

// RelationshipBody : Relationship =
//     ';' | '{' ( ownedRelationship += OwnedAnnotation )* '}'
relationshipBody
    : SEMICOLON
    | LBRACE ownedAnnotation* RBRACE
    ;

// 8.2.2.3 Dependencies Textual Notation

// Dependency =
//     ( ownedRelationship += PrefixMetadataAnnotation )*
//     'dependency' DependencyDeclaration
//     RelationshipBody
dependency
    : prefixMetadataAnnotation*
      DEPENDENCY dependencyDeclaration
      relationshipBody
    ;

// DependencyDeclaration =
//     ( Identification 'from' )?
//     client += [QualifiedName] ( ',' client += [QualifiedName] )* 'to'
//     supplier += [QualifiedName] ( ',' supplier += [QualifiedName] )*
dependencyDeclaration
    : ( identification FROM )?
      client+=qualifiedName ( COMMA client+=qualifiedName )* TO
      supplier+=qualifiedName ( COMMA supplier+=qualifiedName )*
    ;

// 8.2.2.4 Annotations Textual Notation
// 8.2.2.4.1 Annotations

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

// AnnotatingMember : OwningMembership =
//     ownedRelatedElement += AnnotatingElement
annotatingMember
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

// 8.2.2.4.2 Comments and Documentation

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
        ( ABOUT annotation
          ( COMMA annotation )*
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

// 8.2.2.4.3 Textual Representation

// TextualRepresentation =
//     ( 'rep' Identification )?
//     'language' language = STRING_VALUE body = REGULAR_COMMENT
textualRepresentation
    : ( REP identification )?
      LANGUAGE language=STRING_VALUE body=REGULAR_COMMENT
    ;

// 8.2.2.5 Namespaces and Packages Textual Notation
// 8.2.2.5.1 Packages

// RootNamespace : Namespace =
//     PackageBodyElement*
rootNamespace
    : packageBodyElement* EOF
    ;

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
//     ';' | '{' PackageBodyElement* '}'
packageBody
    : SEMICOLON
    | LBRACE packageBodyElement* RBRACE
    ;

// PackageBodyElement : Package =
//     ownedRelationship += PackageMember
//     | ownedRelationship += ElementFilterMember
//     | ownedRelationship += AliasMember
//     | ownedRelationship += Import
packageBodyElement
    : packageMember
    | elementFilterMember
    | aliasMember
    | import_
    ;

// MemberPrefix : Membership =
//     ( visibility = VisibilityIndicator )?
visibility: visibilityIndicator;
memberPrefix: visibility?;

// PackageMember : OwningMembership =
//     MemberPrefix
//     ( ownedRelatedElement += DefinitionElement
//       | ownedRelatedElement += UsageElement )
packageMember
    : memberPrefix
      ( definitionElement
      | usageElement
      )
    ;

// ElementFilterMember : ElementFilterMembership =
//     MemberPrefix
//     'filter' ownedRelatedElement += OwnedExpression ';'
elementFilterMember
    : memberPrefix
      FILTER ownedExpression SEMICOLON
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
      FOR memberElement=qualifiedName
      relationshipBody
    ;

// Import =
//     visibility = VisibilityIndicator
//     'import' ( isImportAll ?= 'all' )?
//     ImportDeclaration
//     RelationshipBody
// LOCAL PATCH (sysml2-experiments): the upstream rule required a mandatory
// visibilityIndicator before 'import', which rejects the spec's own examples
// (e.g. `import ScalarValues::*;`).  Aligned with KerML.g4, which uses the
// optional memberPrefix.
import_
    : memberPrefix
      IMPORT ( isImportAll=ALL )?
      importDeclaration
      relationshipBody
    ;

// ImportDeclaration : Import =
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
    | filterPackage
    ;

// FilterPackage : Package =
//     ownedRelationship += FilterPackageImport
//     ( ownedRelationship += FilterPackageMember )+
// Note: FilterPackageImport is inlined as the import declaration
filterPackage
    : ( membershipImport | qualifiedName DOUBLE_COLON STAR ( DOUBLE_COLON isRecursive=DOUBLE_STAR )? )
      filterPackageMember+
    ;

// FilterPackageMember : ElementFilterMembership =
//     '[' ownedRelatedElement += OwnedExpression ']'
filterPackageMember
    : LBRACKET ownedExpression RBRACKET
    ;

// VisibilityIndicator : VisibilityKind =
//     'public' | 'private' | 'protected'
visibilityIndicator
    : PUBLIC
    | PRIVATE
    | PROTECTED
    ;

// 8.2.2.5.2 Package Elements

// DefinitionElement : Element =
//     Package
//     | LibraryPackage
//     | AnnotatingElement
//     | Dependency
//     | AttributeDefinition
//     | EnumerationDefinition
//     | OccurrenceDefinition
//     | IndividualDefinition
//     | ItemDefinition
//     | PartDefinition
//     | ConnectionDefinition
//     | FlowDefinition
//     | InterfaceDefinition
//     | PortDefinition
//     | ActionDefinition
//     | CalculationDefinition
//     | StateDefinition
//     | ConstraintDefinition
//     | RequirementDefinition
//     | ConcernDefinition
//     | CaseDefinition
//     | AnalysisCaseDefinition
//     | VerificationCaseDefinition
//     | UseCaseDefinition
//     | ViewDefinition
//     | ViewpointDefinition
//     | RenderingDefinition
//     | MetadataDefinition
//     | ExtendedDefinition
definitionElement
    : package
    | libraryPackage
    | annotatingElement
    | dependency
    | attributeDefinition
    | enumerationDefinition
    | occurrenceDefinition
    | individualDefinition
    | itemDefinition
    | partDefinition
    | connectionDefinition
    | flowDefinition
    | allocationDefinition
    | interfaceDefinition
    | portDefinition
    | actionDefinition
    | calculationDefinition
    | stateDefinition
    | constraintDefinition
    | requirementDefinition
    | concernDefinition
    | caseDefinition
    | analysisCaseDefinition
    | verificationCaseDefinition
    | useCaseDefinition
    | viewDefinition
    | viewpointDefinition
    | renderingDefinition
    | metadataDefinition
    | extendedDefinition
    ;

// UsageElement : Usage =
//     NonOccurrenceUsageElement
//     | OccurrenceUsageElement
usageElement
    : nonOccurrenceUsageElement
    | occurrenceUsageElement
    ;

// 8.2.2.6 Definition and Usage Textual Notation
// 8.2.2.6.1 Definitions

// BasicDefinitionPrefix =
//     isAbstract ?= 'abstract' | isVariation ?= 'variation'
basicDefinitionPrefix
    : isAbstract=ABSTRACT
    | isVariation=VARIATION
    ;

// DefinitionExtensionKeyword : Definition =
//     ownedRelationship += PrefixMetadataMember
definitionExtensionKeyword
    : prefixMetadataMember
    ;

// DefinitionPrefix : Definition =
//     BasicDefinitionPrefix? DefinitionExtensionKeyword*
definitionPrefix
    : basicDefinitionPrefix? definitionExtensionKeyword*
    ;

// Definition =
//     DefinitionDeclaration DefinitionBody
definition
    : definitionDeclaration definitionBody
    ;

// DefinitionDeclaration : Definition =
//     Identification SubclassificationPart?
definitionDeclaration
    : identification subclassificationPart?
    ;

// DefinitionBody : Type =
//     ';' | '{' DefinitionBodyItem* '}'
definitionBody
    : SEMICOLON
    | LBRACE definitionBodyItem* RBRACE
    ;

// DefinitionBodyItem : Type =
//     ownedRelationship += DefinitionMember
//     | ownedRelationship += VariantUsageMember
//     | ownedRelationship += NonOccurrenceUsageMember
//     | ( ownedRelationship += SourceSuccessionMember )?
//       ownedRelationship += OccurrenceUsageMember
//     | ownedRelationship += AliasMember
//     | ownedRelationship += Import
definitionBodyItem
    : definitionMember
    | variantUsageMember
    | nonOccurrenceUsageMember
    | sourceSuccessionMember? occurrenceUsageMember
    | aliasMember
    | import_
    ;

// DefinitionMember : OwningMembership =
//     MemberPrefix
//     ownedRelatedElement += DefinitionElement
definitionMember
    : memberPrefix
      definitionElement
    ;

// VariantUsageMember : VariantMembership =
//     MemberPrefix 'variant'
//     ownedVariantUsage = VariantUsageElement
variantUsageMember
    : memberPrefix VARIANT
      variantUsageElement
    ;

// NonOccurrenceUsageMember : FeatureMembership =
//     MemberPrefix
//     ownedRelatedElement += NonOccurrenceUsageElement
nonOccurrenceUsageMember
    : memberPrefix
      nonOccurrenceUsageElement
    ;

// OccurrenceUsageMember : FeatureMembership =
//     MemberPrefix
//     ownedRelatedElement += OccurrenceUsageElement
occurrenceUsageMember
    : memberPrefix
      occurrenceUsageElement
    ;

// StructureUsageMember : FeatureMembership =
//     MemberPrefix
//     ownedRelatedElement += StructureUsageElement
structureUsageMember
    : memberPrefix
      structureUsageElement
    ;

// BehaviorUsageMember : FeatureMembership =
//     MemberPrefix
//     ownedRelatedElement += BehaviorUsageElement
behaviorUsageMember
    : memberPrefix
      behaviorUsageElement
    ;

// 8.2.2.6.2 Usages

// FeatureDirection : FeatureDirectionKind =
//     'in' | 'out' | 'inout'
featureDirection
    : IN
    | OUT
    | INOUT
    ;

// RefPrefix : Usage =
//     ( direction = FeatureDirection )?
//     ( isDerived ?= 'derived' )?
//     ( isAbstract ?= 'abstract' | isVariation ?= 'variation' )?
//     ( isConstant ?= 'constant' )?
refPrefix
    : featureDirection?
      DERIVED?
      ( ABSTRACT | VARIATION )?
      CONSTANT?
    ;

// BasicUsagePrefix : Usage =
//     RefPrefix
//     ( isReference ?= 'ref' )?
basicUsagePrefix
    : refPrefix
      REF?
    ;

// EndUsagePrefix : Usage =
//     isEnd ?= 'end' ( ownedRelationship += OwnedCrossFeatureMember )?
endUsagePrefix
    : END ownedCrossFeatureMember?
    ;

// OwnedCrossFeatureMember : OwningMembership =
//     ownedRelatedElement += OwnedCrossFeature
ownedCrossFeatureMember
    : ownedCrossFeature
    ;

// OwnedCrossFeature : ReferenceUsage =
//     BasicUsagePrefix UsageDeclaration
ownedCrossFeature
    : basicUsagePrefix usageDeclaration
    ;

// UsageExtensionKeyword : Usage =
//     ownedRelationship += PrefixMetadataMember
usageExtensionKeyword
    : prefixMetadataMember
    ;

// UnextendedUsagePrefix : Usage =
//     EndUsagePrefix | BasicUsagePrefix
unextendedUsagePrefix
    : endUsagePrefix
    | basicUsagePrefix
    ;

// UsagePrefix : Usage =
//     UnextendedUsagePrefix UsageExtensionKeyword*
usagePrefix
    : unextendedUsagePrefix usageExtensionKeyword*
    ;

// Usage : Usage =
//     UsageDeclaration UsageCompletion
usage
    : usageDeclaration usageCompletion
    ;

// UsageDeclaration : Usage =
//     Identification FeatureSpecializationPart?
usageDeclaration
    : identification featureSpecializationPart?
    ;

// UsageCompletion : Usage =
//     ValuePart? UsageBody
usageCompletion
    : valuePart? usageBody
    ;

// UsageBody : Usage =
//     DefinitionBody
usageBody
    : definitionBody
    ;

// ValuePart : Feature =
//     ownedRelationship += FeatureValue
valuePart
    : featureValue
    ;

// FeatureValue : FeatureValue =
//     ( '='
//     | isInitial ?= ':='
//     | isDefault ?= 'default' ( '=' | isInitial ?= ':=' )?
//     )
//     ownedRelatedElement += OwnedExpression
//     ( 'meta' metaType = QualifiedName )?  // Optional metatype specification
featureValue
    : ( EQUALS
      | COLON_EQUALS
      | DEFAULT ( EQUALS | COLON_EQUALS )?
      )
      ownedExpression
      ( META metaType=qualifiedName )?
    ;

// 8.2.2.6.3 Reference Usages

// DefaultReferenceUsage : ReferenceUsage =
//     ( EndUsagePrefix | RefPrefix ) Usage
// NOTE: Extended from spec's RefPrefix to also support EndUsagePrefix,
// allowing 'end <name> : <Type> :>> <redefinition>;' syntax (e.g., in Allocations.sysml)
defaultReferenceUsage
    : ( endUsagePrefix | refPrefix ) usage
    ;

// ReferenceUsage =
//     ( EndUsagePrefix | RefPrefix )
//     'ref' Usage
referenceUsage
    : ( endUsagePrefix | refPrefix )
      REF usage
    ;

// VariantReference : ReferenceUsage =
//     ownedRelationship += OwnedReferenceSubsetting
//     FeatureSpecialization* UsageBody
variantReference
    : ownedReferenceSubsetting
      featureSpecialization* usageBody
    ;

// 8.2.2.6.4 Body Elements

// NonOccurrenceUsageElement : Usage =
//     DefaultReferenceUsage
//     | ReferenceUsage
//     | AttributeUsage
//     | EnumerationUsage
//     | BindingConnectorAsUsage
//     | SuccessionAsUsage
//     | ExtendedUsage
nonOccurrenceUsageElement
    : defaultReferenceUsage
    | referenceUsage
    | attributeUsage
    | enumerationUsage
    | bindingConnectorAsUsage
    | successionAsUsage
    | extendedUsage
    ;

// OccurrenceUsageElement : Usage =
//     StructureUsageElement | BehaviorUsageElement
occurrenceUsageElement
    : structureUsageElement
    | behaviorUsageElement
    ;

// StructureUsageElement : Usage =
//     OccurrenceUsage
//     | IndividualUsage
//     | PortionUsage
//     | EventOccurrenceUsage
//     | ItemUsage
//     | PartUsage
//     | ViewUsage
//     | RenderingUsage
//     | PortUsage
//     | ConnectionUsage
//     | InterfaceUsage
//     | AllocationUsage
//     | Message
//     | FlowUsage
//     | SuccessionFlowUsage
structureUsageElement
    : occurrenceUsage
    | individualUsage
    | portionUsage
    | eventOccurrenceUsage
    | itemUsage
    | partUsage
    | viewUsage
    | renderingUsage
    | portUsage
    | connectionUsage
    | interfaceUsage
    | allocationUsage
    | message
    | flowUsage
    | successionFlowUsage
    ;

// BehaviorUsageElement : Usage =
//     ActionUsage
//     | CalculationUsage
//     | StateUsage
//     | ConstraintUsage
//     | RequirementUsage
//     | ConcernUsage
//     | CaseUsage
//     | AnalysisCaseUsage
//     | VerificationCaseUsage
//     | UseCaseUsage
//     | ViewpointUsage
//     | PerformActionUsage
//     | ExhibitStateUsage
//     | IncludeUseCaseUsage
//     | AssertConstraintUsage
//     | SatisfyRequirementUsage
behaviorUsageElement
    : actionUsage
    | calculationUsage
    | stateUsage
    | constraintUsage
    | requirementUsage
    | concernUsage
    | caseUsage
    | analysisCaseUsage
    | verificationCaseUsage
    | useCaseUsage
    | viewpointUsage
    | performActionUsage
    | exhibitStateUsage
    | includeUseCaseUsage
    | assertConstraintUsage
    | satisfyRequirementUsage
    ;

// VariantUsageElement : Usage =
//     VariantReference
//     | ReferenceUsage
//     | AttributeUsage
//     | BindingConnectorAsUsage
//     | SuccessionAsUsage
//     | OccurrenceUsage
//     | IndividualUsage
//     | PortionUsage
//     | EventOccurrenceUsage
//     | ItemUsage
//     | PartUsage
//     | ViewUsage
//     | RenderingUsage
//     | PortUsage
//     | ConnectionUsage
//     | InterfaceUsage
//     | AllocationUsage
//     | Message
//     | FlowUsage
//     | SuccessionFlowUsage
//     | BehaviorUsageElement
variantUsageElement
    : variantReference
    | referenceUsage
    | attributeUsage
    | bindingConnectorAsUsage
    | successionAsUsage
    | occurrenceUsage
    | individualUsage
    | portionUsage
    | eventOccurrenceUsage
    | itemUsage
    | partUsage
    | viewUsage
    | renderingUsage
    | portUsage
    | connectionUsage
    | interfaceUsage
    | allocationUsage
    | message
    | flowUsage
    | successionFlowUsage
    | behaviorUsageElement
    ;

// 8.2.2.6.5 Specialization

// SubclassificationPart : Classifier =
//     SPECIALIZES ownedRelationship += OwnedSubclassification
//     ( ',' ownedRelationship += OwnedSubclassification )*
subclassificationPart
    : specializesToken ownedSubclassification
      ( COMMA ownedSubclassification )*
    ;

// OwnedSubclassification : Subclassification =
//     superClassifier = [QualifiedName]
ownedSubclassification
    : superClassifier=qualifiedName
    ;

// FeatureSpecializationPart : Feature =
//     FeatureSpecialization+ MultiplicityPart? FeatureSpecialization*
//     | MultiplicityPart FeatureSpecialization*
featureSpecializationPart
    : featureSpecialization+ multiplicityPart? featureSpecialization*
    | multiplicityPart featureSpecialization*
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
//     TypedBy ( ',' ownedRelationship += FeatureTyping )*
typings
    : typedBy ( COMMA featureTyping )*
    ;

// TypedBy : Feature =
//     DEFINED_BY ownedRelationship += FeatureTyping
typedBy
    : definedByToken featureTyping
    ;

// FeatureTyping =
//     OwnedFeatureTyping | ConjugatedPortTyping
featureTyping
    : ownedFeatureTyping
    | conjugatedPortTyping
    ;

// OwnedFeatureTyping : FeatureTyping =
//     type = [QualifiedName]
//     | type = OwnedFeatureChain
//       { ownedRelatedElement += type }
ownedFeatureTyping
    : qualifiedName
    | ownedFeatureChain
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

// OwnedSubsetting : Subsetting =
//     subsettedFeature = [QualifiedName]
//     | subsettedFeature = OwnedFeatureChain
//       { ownedRelatedElement += subsettedFeature }
ownedSubsetting
    : qualifiedName
    | ownedFeatureChain
    ;

// References : Feature =
//     REFERENCES ownedRelationship += OwnedReferenceSubsetting
references
    : referencesToken ownedReferenceSubsetting
    ;

// OwnedReferenceSubsetting : ReferenceSubsetting =
//     referencedFeature = [QualifiedName]
//     | referencedFeature = OwnedFeatureChain
//       { ownedRelatedElement += referencedFeature }
ownedReferenceSubsetting
    : qualifiedName
    | ownedFeatureChain
    ;

// Crosses : Feature =
//     CROSSES ownedRelationship += OwnedCrossSubsetting
crosses
    : crossesToken ownedCrossSubsetting
    ;

// OwnedCrossSubsetting : CrossSubsetting =
//     crossedFeature = [QualifiedName]
//     | crossedFeature = OwnedFeatureChain
//       { ownedRelatedElement += crossedFeature }
ownedCrossSubsetting
    : qualifiedName
    | ownedFeatureChain
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

// OwnedRedefinition : Redefinition =
//     redefinedFeature = [QualifiedName]
//     | redefinedFeature = OwnedFeatureChain
//       { ownedRelatedElement += redefinedFeature }
ownedRedefinition
    : qualifiedName
    | ownedFeatureChain
    ;

// OwnedFeatureChain : Feature =
//     ownedRelationship += OwnedFeatureChaining
//     ( '.' ownedRelationship += OwnedFeatureChaining )+
ownedFeatureChain
    : ownedFeatureChaining
      ( DOT ownedFeatureChaining )+
    ;

// OwnedFeatureChaining : FeatureChaining =
//     chainingFeature = [QualifiedName]
ownedFeatureChaining
    : chainingFeature=qualifiedName
    ;

// 8.2.2.6.6 Multiplicity

// MultiplicityPart : Feature =
//     ownedRelationship += OwnedMultiplicity
//     | ( ownedRelationship += OwnedMultiplicity )?
//       ( isOrdered ?= 'ordered' ( { isUnique = false } 'nonunique' )?
//       | { isUnique = false } 'nonunique' ( isOrdered ?= 'ordered' )? )
multiplicityPart
    : ownedMultiplicity
    | ownedMultiplicity?
      ( isOrdered=ORDERED ( isNonunique=NONUNIQUE )?
      | isNonunique=NONUNIQUE ( isOrdered=ORDERED )?
      )
    ;

// OwnedMultiplicity : OwningMembership =
//     ownedRelatedElement += MultiplicityRange
ownedMultiplicity
    : multiplicityRange
    ;

// MultiplicityRange =
//     '[' ( ownedRelationship += MultiplicityExpressionMember '..' )?
//     ownedRelationship += MultiplicityExpressionMember ']'
multiplicityRange
    : LBRACKET ( multiplicityExpressionMember DOUBLE_DOT )?
      multiplicityExpressionMember RBRACKET
    ;

// MultiplicityExpressionMember : OwningMembership =
//     ownedRelatedElement += ( LiteralExpression | FeatureReferenceExpression )
multiplicityExpressionMember
    : literalExpression
    | featureReferenceExpression
    ;

// 8.2.2.7 Attributes Textual Notation

// AttributeDefinition : AttributeDefinition =
//     DefinitionPrefix 'attribute' 'def' Definition
attributeDefinition
    : definitionPrefix ATTRIBUTE DEF definition
    ;

// AttributeUsage : AttributeUsage =
//     UsagePrefix 'attribute' Usage
attributeUsage
    : usagePrefix ATTRIBUTE usage
    ;

// 8.2.2.8 Enumerations Textual Notation

// EnumerationDefinition =
//     DefinitionExtensionKeyword*
//     'enum' 'def' DefinitionDeclaration EnumerationBody
enumerationDefinition
    : definitionExtensionKeyword*
      ENUM DEF definitionDeclaration enumerationBody
    ;

// EnumerationBody : EnumerationDefinition =
//     ';'
//     | '{' ( ownedRelationship += AnnotatingMember
//           | ownedRelationship += EnumerationUsageMember )*
//       '}'
enumerationBody
    : SEMICOLON
    | LBRACE ( annotatingMember
             | enumerationUsageMember
             )*
      RBRACE
    ;

// EnumerationUsageMember : VariantMembership =
//     MemberPrefix ownedRelatedElement += EnumeratedValue
enumerationUsageMember
    : memberPrefix enumeratedValue
    ;

// EnumeratedValue : EnumerationUsage =
//     'enum'? Usage
enumeratedValue
    : ENUM? usage
    ;

// EnumerationUsage : EnumerationUsage =
//     UsagePrefix 'enum' Usage
enumerationUsage
    : usagePrefix ENUM usage
    ;

// 8.2.2.9 Occurrences Textual Notation
// 8.2.2.9.1 Occurrence Definitions

// OccurrenceDefinitionPrefix : OccurrenceDefinition =
//     BasicDefinitionPrefix?
//     ( isIndividual ?= 'individual'
//       ownedRelationship += EmptyMultiplicityMember
//     )?
//     DefinitionExtensionKeyword*
occurrenceDefinitionPrefix
    : basicDefinitionPrefix?
      ( isIndividual=INDIVIDUAL
        emptyMultiplicityMember
      )?
      definitionExtensionKeyword*
    ;

// OccurrenceDefinition =
//     OccurrenceDefinitionPrefix 'occurrence' 'def' Definition
occurrenceDefinition
    : occurrenceDefinitionPrefix OCCURRENCE DEF definition
    ;

// IndividualDefinition : OccurrenceDefinition =
//     BasicDefinitionPrefix? isIndividual ?= 'individual'
//     DefinitionExtensionKeyword* 'def' Definition
//     ownedRelationship += EmptyMultiplicityMember
individualDefinition
    : basicDefinitionPrefix? isIndividual=INDIVIDUAL
      definitionExtensionKeyword* DEF definition
      emptyMultiplicityMember
    ;

// EmptyMultiplicityMember : OwningMembership =
//     ownedRelatedElement += EmptyMultiplicity
emptyMultiplicityMember
    : emptyMultiplicity
    ;

// EmptyMultiplicity : Multiplicity =
//     { }
emptyMultiplicity
    : // empty
    ;

// 8.2.2.9.2 Occurrence Usages

// OccurrenceUsagePrefix : OccurrenceUsage =
//     UnextendedUsagePrefix
//     ( isIndividual ?= 'individual' )?
//     ( portionKind = PortionKind
//       { isPortion = true }
//     )?
//     UsageExtensionKeyword*
// NOTE: Uses unextendedUsagePrefix (endUsagePrefix | basicUsagePrefix)
// to support 'end <name> [mult] occurrence ...' with cross feature members
occurrenceUsagePrefix
    : unextendedUsagePrefix
      INDIVIDUAL?
      portionKindToken?
      usageExtensionKeyword*
    ;

// OccurrenceUsage : OccurrenceUsage =
//     OccurrenceUsagePrefix 'occurrence' Usage
occurrenceUsage
    : occurrenceUsagePrefix OCCURRENCE usage
    ;

// IndividualUsage : OccurrenceUsage =
//     BasicUsagePrefix isIndividual ?= 'individual'
//     UsageExtensionKeyword* Usage
individualUsage
    : basicUsagePrefix INDIVIDUAL
      usageExtensionKeyword* usage
    ;

// PortionUsage : OccurrenceUsage =
//     BasicUsagePrefix ( isIndividual ?= 'individual' )?
//     portionKind = PortionKind
//     UsageExtensionKeyword* Usage
//     { isPortion = true }
portionUsage
    : basicUsagePrefix INDIVIDUAL?
      portionKindToken
      usageExtensionKeyword* usage
    ;

// PortionKind =
//     'snapshot' | 'timeslice'
portionKindToken
    : SNAPSHOT
    | TIMESLICE
    ;

// EventOccurrenceUsage : EventOccurrenceUsage =
//     OccurrenceUsagePrefix 'event'
//     ( ownedRelationship += OwnedReferenceSubsetting
//       FeatureSpecializationPart?
//     | 'occurrence' UsageDeclaration? )
//     UsageCompletion
eventOccurrenceUsage
    : occurrenceUsagePrefix EVENT
      ( ownedReferenceSubsetting featureSpecializationPart?
      | OCCURRENCE usageDeclaration?
      )
      usageCompletion
    ;

// 8.2.2.9.3 Occurrence Successions

// SourceSuccessionMember : FeatureMembership =
//     'then' ownedRelatedElement += SourceSuccession
sourceSuccessionMember
    : THEN sourceSuccession
    ;

// SourceSuccession : SuccessionAsUsage =
//     ownedRelationship += SourceEndMember
sourceSuccession
    : sourceEndMember
    ;

// SourceEndMember : EndFeatureMembership =
//     ownedRelatedElement += SourceEnd
sourceEndMember
    : sourceEnd
    ;

// SourceEnd : ReferenceUsage =
//     ( ownedRelationship += OwnedMultiplicity )?
sourceEnd
    : ownedMultiplicity?
    ;

// 8.2.2.10 Items Textual Notation

// ItemDefinition =
//     OccurrenceDefinitionPrefix
//     'item' 'def' Definition
itemDefinition
    : occurrenceDefinitionPrefix
      ITEM DEF definition
    ;

// ItemUsage =
//     OccurrenceUsagePrefix 'item' Usage
itemUsage
    : occurrenceUsagePrefix ITEM usage
    ;

// 8.2.2.11 Parts Textual Notation

// PartDefinition =
//     OccurrenceDefinitionPrefix 'part' 'def' Definition
partDefinition
    : occurrenceDefinitionPrefix PART DEF definition
    ;

// PartUsage =
//     OccurrenceUsagePrefix 'part' Usage
partUsage
    : occurrenceUsagePrefix PART usage
    ;

// 8.2.2.12 Ports Textual Notation

// PortDefinition =
//     DefinitionPrefix 'port' 'def' Definition
//     ownedRelationship += ConjugatedPortDefinitionMember
// Note: ConjugatedPortDefinitionMember is implicitly created during semantic analysis
portDefinition
    : definitionPrefix PORT DEF definition
    ;

// ConjugatedPortDefinitionMember : OwningMembership =
//     ownedRelatedElement += ConjugatedPortDefinition
// Note: Created implicitly for every PortDefinition
conjugatedPortDefinitionMember
    : conjugatedPortDefinition
    ;

// ConjugatedPortDefinition =
//     ownedRelationship += PortConjugation
// Note: Created implicitly with name ~<PortDefinitionName>
conjugatedPortDefinition
    : portConjugation
    ;

// PortConjugation = {}
// Note: Empty semantic construct
portConjugation
    : // empty
    ;

// PortUsage =
//     OccurrenceUsagePrefix 'port' Usage
portUsage
    : occurrenceUsagePrefix PORT usage
    ;

// ConjugatedPortTyping : ConjugatedPortTyping =
//     '~' originalPortDefinition = ~[QualifiedName]
// Note: The ~ prefix indicates resolution to the conjugated port definition
conjugatedPortTyping
    : TILDE qualifiedName
    ;

// 8.2.2.13 Connections Textual Notation
// 8.2.2.13.1 Connection Definition and Usage

// ConnectionDefinition =
//     OccurrenceDefinitionPrefix 'connection' 'def' Definition
connectionDefinition
    : occurrenceDefinitionPrefix CONNECTION DEF definition
    ;

// ConnectionUsage =
//     OccurrenceUsagePrefix
//     ( 'connection' UsageDeclaration ValuePart?
//       ( 'connect' ConnectorPart )?
//     | 'connect' ConnectorPart )
//     UsageBody
connectionUsage
    : occurrenceUsagePrefix
      ( CONNECTION usageDeclaration valuePart?
        ( CONNECT connectorPart )?
      | CONNECT connectorPart
      )
      usageBody
    ;

// ConnectorPart : ConnectionUsage =
//     BinaryConnectorPart | NaryConnectorPart
connectorPart
    : binaryConnectorPart
    | naryConnectorPart
    ;

// BinaryConnectorPart : ConnectionUsage =
//     ownedRelationship += ConnectorEndMember 'to'
//     ownedRelationship += ConnectorEndMember
binaryConnectorPart
    : connectorEndMember TO connectorEndMember
    ;

// NaryConnectorPart : ConnectionUsage =
//     '(' ownedRelationship += ConnectorEndMember ','
//     ownedRelationship += ConnectorEndMember
//     ( ',' ownedRelationship += ConnectorEndMember )* ')'
naryConnectorPart
    : LPAREN connectorEndMember COMMA
      connectorEndMember
      ( COMMA connectorEndMember )* RPAREN
    ;

// ConnectorEndMember : EndFeatureMembership =
//     ownedRelatedElement += ConnectorEnd
connectorEndMember
    : connectorEnd
    ;

// ConnectorEnd : ReferenceUsage =
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

// 8.2.2.13.2 Binding Connectors

// BindingConnectorAsUsage =
//     UsagePrefix ( 'binding' UsageDeclaration )?
//     'bind' ownedRelationship += ConnectorEndMember
//     '=' ownedRelationship += ConnectorEndMember
//     UsageBody
bindingConnectorAsUsage
    : usagePrefix ( BINDING usageDeclaration )?
      BIND connectorEndMember
      EQUALS connectorEndMember
      usageBody
    ;

// 8.2.2.13.3 Successions

// SuccessionAsUsage =
//     UsagePrefix ( 'succession' UsageDeclaration )?
//     'first' ownedRelationship += ConnectorEndMember
//     'then' ownedRelationship += ConnectorEndMember
//     UsageBody
successionAsUsage
    : usagePrefix ( SUCCESSION usageDeclaration )?
      FIRST connectorEndMember
      THEN connectorEndMember
      usageBody
    ;

// 8.2.2.14 Interfaces Textual Notation
// 8.2.2.14.1 Interface Definitions

// InterfaceDefinition =
//     OccurrenceDefinitionPrefix 'interface' 'def'
//     DefinitionDeclaration InterfaceBody
interfaceDefinition
    : occurrenceDefinitionPrefix INTERFACE DEF
      definitionDeclaration interfaceBody
    ;

// InterfaceBody : Type =
//     ';' | '{' InterfaceBodyItem* '}'
interfaceBody
    : SEMICOLON
    | LBRACE interfaceBodyItem* RBRACE
    ;

// InterfaceBodyItem : Type =
//     ownedRelationship += DefinitionMember
//     | ownedRelationship += VariantUsageMember
//     | ownedRelationship += InterfaceNonOccurrenceUsageMember
//     | ( ownedRelationship += SourceSuccessionMember )?
//       ownedRelationship += InterfaceOccurrenceUsageMember
//     | ownedRelationship += AliasMember
//     | ownedRelationship += Import
interfaceBodyItem
    : definitionMember
    | variantUsageMember
    | interfaceNonOccurrenceUsageMember
    | sourceSuccessionMember? interfaceOccurrenceUsageMember
    | aliasMember
    | import_
    ;

// InterfaceNonOccurrenceUsageMember : FeatureMembership =
//     MemberPrefix ownedRelatedElement += InterfaceNonOccurrenceUsageElement
interfaceNonOccurrenceUsageMember
    : memberPrefix interfaceNonOccurrenceUsageElement
    ;

// InterfaceNonOccurrenceUsageElement : Usage =
//     ReferenceUsage
//     | AttributeUsage
//     | EnumerationUsage
//     | BindingConnectorAsUsage
//     | SuccessionAsUsage
interfaceNonOccurrenceUsageElement
    : referenceUsage
    | attributeUsage
    | enumerationUsage
    | bindingConnectorAsUsage
    | successionAsUsage
    ;

// InterfaceOccurrenceUsageMember : FeatureMembership =
//     MemberPrefix ownedRelatedElement += InterfaceOccurrenceUsageElement
interfaceOccurrenceUsageMember
    : memberPrefix interfaceOccurrenceUsageElement
    ;

// InterfaceOccurrenceUsageElement : Usage =
//     DefaultInterfaceEnd | StructureUsageElement | BehaviorUsageElement
interfaceOccurrenceUsageElement
    : defaultInterfaceEnd
    | structureUsageElement
    | behaviorUsageElement
    ;

// DefaultInterfaceEnd : PortUsage =
//     isEnd ?= 'end' Usage
defaultInterfaceEnd
    : isEnd=END usage
    ;

// 8.2.2.14.2 Interface Usages

// InterfaceUsage =
//     OccurrenceUsagePrefix 'interface'
//     InterfaceUsageDeclaration InterfaceBody
interfaceUsage
    : occurrenceUsagePrefix INTERFACE
      interfaceUsageDeclaration interfaceBody
    ;

// InterfaceUsageDeclaration : InterfaceUsage =
//     UsageDeclaration ValuePart?
//     ( 'connect' InterfacePart )?
//     | InterfacePart
interfaceUsageDeclaration
    : usageDeclaration valuePart?
      ( CONNECT interfacePart )?
    | interfacePart
    ;

// InterfacePart : InterfaceUsage =
//     BinaryInterfacePart | NaryInterfacePart
interfacePart
    : binaryInterfacePart
    | naryInterfacePart
    ;

// BinaryInterfacePart : InterfaceUsage =
//     ownedRelationship += InterfaceEndMember 'to'
//     ownedRelationship += InterfaceEndMember
binaryInterfacePart
    : interfaceEndMember TO interfaceEndMember
    ;

// NaryInterfacePart : InterfaceUsage =
//     '(' ownedRelationship += InterfaceEndMember ','
//     ownedRelationship += InterfaceEndMember
//     ( ',' ownedRelationship += InterfaceEndMember )* ')'
naryInterfacePart
    : LPAREN interfaceEndMember COMMA
      interfaceEndMember
      ( COMMA interfaceEndMember )* RPAREN
    ;

// InterfaceEndMember : EndFeatureMembership =
//     ownedRelatedElement += InterfaceEnd
interfaceEndMember
    : interfaceEnd
    ;

// InterfaceEnd : PortUsage =
//     ( ownedRelationship += OwnedCrossMultiplicityMember )?
//     ( declaredName = NAME REFERENCES )?
//     ownedRelationship += OwnedReferenceSubsetting
interfaceEnd
    : ownedCrossMultiplicityMember?
      ( declaredName=NAME referencesToken )?
      ownedReferenceSubsetting
    ;

// 8.2.2.15 Allocations Textual Notation

// AllocationDefinition =
//     OccurrenceDefinitionPrefix 'allocation' 'def' Definition
allocationDefinition
    : occurrenceDefinitionPrefix ALLOCATION DEF definition
    ;

// AllocationUsage =
//     OccurrenceUsagePrefix
//     AllocationUsageDeclaration UsageBody
allocationUsage
    : occurrenceUsagePrefix
      allocationUsageDeclaration usageBody
    ;

// AllocationUsageDeclaration : AllocationUsage =
//     'allocation' UsageDeclaration
//     ( 'allocate' ConnectorPart )?
//     | 'allocate' ConnectorPart
allocationUsageDeclaration
    : ALLOCATION usageDeclaration
      ( ALLOCATE connectorPart )?
    | ALLOCATE connectorPart
    ;

// 8.2.2.16 Flows Textual Notation

// FlowDefinition =
//     OccurrenceDefinitionPrefix 'flow' 'def' Definition
flowDefinition
    : occurrenceDefinitionPrefix FLOW DEF definition
    ;

// Message : FlowUsage =
//     OccurrenceUsagePrefix 'message'
//     MessageDeclaration DefinitionBody
//     { isAbstract = true }
message
    : occurrenceUsagePrefix MESSAGE
      messageDeclaration definitionBody
    ;

// MessageDeclaration : FlowUsage =
//     UsageDeclaration ValuePart?
//     ( 'of' ownedRelationship += FlowPayloadFeatureMember )?
//     ( 'from' ownedRelationship += MessageEventMember
//       'to' ownedRelationship += MessageEventMember
//     )?
//     | ownedRelationship += MessageEventMember 'to'
//       ownedRelationship += MessageEventMember
messageDeclaration
    : usageDeclaration valuePart?
      ( OF flowPayloadFeatureMember )?
      ( FROM messageEventMember
        TO messageEventMember
      )?
    | messageEventMember TO messageEventMember
    ;

// MessageEventMember : ParameterMembership =
//     ownedRelatedElement += MessageEvent
messageEventMember
    : messageEvent
    ;

// MessageEvent : EventOccurrenceUsage =
//     ownedRelationship += OwnedReferenceSubsetting
messageEvent
    : ownedReferenceSubsetting
    ;

// FlowUsage =
//     OccurrenceUsagePrefix 'flow'
//     FlowDeclaration DefinitionBody
flowUsage
    : occurrenceUsagePrefix FLOW
      flowDeclaration definitionBody
    ;

// SuccessionFlowUsage =
//     OccurrenceUsagePrefix 'succession' 'flow'
//     FlowDeclaration DefinitionBody
successionFlowUsage
    : occurrenceUsagePrefix SUCCESSION FLOW
      flowDeclaration definitionBody
    ;

// FlowDeclaration : FlowUsage =
//     UsageDeclaration ValuePart?
//     ( 'of' ownedRelationship += FlowPayloadFeatureMember )?
//     ( 'from' ownedRelationship += FlowEndMember
//       'to' ownedRelationship += FlowEndMember )?
//     | ownedRelationship += FlowEndMember 'to'
//       ownedRelationship += FlowEndMember
flowDeclaration
    : usageDeclaration valuePart?
      ( OF flowPayloadFeatureMember )?
      ( FROM flowEndMember
        TO flowEndMember )?
    | flowEndMember TO flowEndMember
    ;

// FlowPayloadFeatureMember : FeatureMembership =
//     ownedRelatedElement += FlowPayloadFeature
flowPayloadFeatureMember
    : flowPayloadFeature
    ;

// FlowPayloadFeature : PayloadFeature =
//     PayloadFeature
flowPayloadFeature
    : payloadFeature
    ;

// PayloadFeature : Feature =
//     Identification? PayloadFeatureSpecializationPart
//     ValuePart?
//     | ownedRelationship += OwnedFeatureTyping
//       ( ownedRelationship += OwnedMultiplicity )?
//     | ownedRelationship += OwnedMultiplicity
//       ownedRelationship += OwnedFeatureTyping
payloadFeature
    : identification? payloadFeatureSpecializationPart
      valuePart?
    | ownedFeatureTyping
      ownedMultiplicity?
    | ownedMultiplicity
      ownedFeatureTyping
    ;

// PayloadFeatureSpecializationPart : Feature =
//     ( -> FeatureSpecialization )+ MultiplicityPart?
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
//     ( ownedRelationship += FlowEndSubsetting )?
//     ownedRelationship += FlowFeatureMember
flowEnd
    : flowEndSubsetting?
      flowFeatureMember
    ;

// FlowEndSubsetting : ReferenceSubsetting =
//     referencedFeature = [QualifiedName]
//     | referencedFeature = FeatureChainPrefix
//       { ownedRelatedElement += referencedFeature }
flowEndSubsetting
    : qualifiedName
    | featureChainPrefix
    ;

// FeatureChainPrefix : Feature =
//     ( ownedRelationship += OwnedFeatureChaining '.' )+
//     ownedRelationship += OwnedFeatureChaining '.'
featureChainPrefix
    : ( ownedFeatureChaining DOT )+
      ownedFeatureChaining DOT
    ;

// FlowFeatureMember : FeatureMembership =
//     ownedRelatedElement += FlowFeature
flowFeatureMember
    : flowFeature
    ;

// FlowFeature : ReferenceUsage =
//     ownedRelationship += FlowFeatureRedefinition
flowFeature
    : flowFeatureRedefinition
    ;

// FlowFeatureRedefinition : Redefinition =
//     redefinedFeature = [QualifiedName]
flowFeatureRedefinition
    : redefinedFeature=qualifiedName
    ;

// 8.2.2.17 Actions Textual Notation
// 8.2.2.17.1 Action Definitions

// ActionDefinition =
//     OccurrenceDefinitionPrefix 'action' 'def'
//     DefinitionDeclaration ActionBody
actionDefinition
    : occurrenceDefinitionPrefix ACTION DEF
      definitionDeclaration actionBody
    ;

// ActionBody : Type =
//     ';' | '{' ActionBodyItem* '}'
actionBody
    : SEMICOLON
    | LBRACE actionBodyItem* RBRACE
    ;

// ActionBodyItem : Type =
//     NonBehaviorBodyItem
//     | ownedRelationship += InitialNodeMember
//       ( ownedRelationship += ActionTargetSuccessionMember )*
//     | ( ownedRelationship += SourceSuccessionMember )?
//       ownedRelationship += ActionBehaviorMember
//       ( ownedRelationship += ActionTargetSuccessionMember )*
//     | ownedRelationship += GuardedSuccessionMember
actionBodyItem
    : nonBehaviorBodyItem
    | initialNodeMember
      actionTargetSuccessionMember*
    | sourceSuccessionMember?
      actionBehaviorMember
      actionTargetSuccessionMember*
    | guardedSuccessionMember
    ;

// NonBehaviorBodyItem =
//     ownedRelationship += Import
//     | ownedRelationship += AliasMember
//     | ownedRelationship += DefinitionMember
//     | ownedRelationship += VariantUsageMember
//     | ownedRelationship += NonOccurrenceUsageMember
//     | ( ownedRelationship += SourceSuccessionMember )?
//       ownedRelationship += StructureUsageMember
nonBehaviorBodyItem
    : import_
    | aliasMember
    | definitionMember
    | variantUsageMember
    | nonOccurrenceUsageMember
    | sourceSuccessionMember? structureUsageMember
    ;

// ActionBehaviorMember : FeatureMembership =
//     BehaviorUsageMember | ActionNodeMember
actionBehaviorMember
    : behaviorUsageMember
    | actionNodeMember
    ;

// InitialNodeMember : FeatureMembership =
//     MemberPrefix 'first' memberFeature = [QualifiedName]
//     RelationshipBody
initialNodeMember
    : memberPrefix FIRST memberFeature=qualifiedName
      relationshipBody
    ;

// ActionNodeMember : FeatureMembership =
//     MemberPrefix ownedRelatedElement += ActionNode
actionNodeMember
    : memberPrefix actionNode
    ;

// ActionTargetSuccessionMember : FeatureMembership =
//     MemberPrefix ownedRelatedElement += ActionTargetSuccession
actionTargetSuccessionMember
    : memberPrefix actionTargetSuccession
    ;

// GuardedSuccessionMember : FeatureMembership =
//     MemberPrefix ownedRelatedElement += GuardedSuccession
guardedSuccessionMember
    : memberPrefix guardedSuccession
    ;

// 8.2.2.17.2 Action Usages

// ActionUsage =
//     OccurrenceUsagePrefix 'action'
//     ActionUsageDeclaration ActionBody
actionUsage
    : occurrenceUsagePrefix ACTION
      actionUsageDeclaration actionBody
    ;

// ActionUsageDeclaration : ActionUsage =
//     UsageDeclaration ValuePart?
actionUsageDeclaration
    : usageDeclaration valuePart?
    ;

// PerformActionUsage =
//     OccurrenceUsagePrefix 'perform'
//     PerformActionUsageDeclaration ActionBody
performActionUsage
    : occurrenceUsagePrefix PERFORM
      performActionUsageDeclaration actionBody
    ;

// PerformActionUsageDeclaration : PerformActionUsage =
//     ( ownedRelationship += OwnedReferenceSubsetting
//       FeatureSpecializationPart?
//     | 'action' UsageDeclaration )
//     ValuePart?
performActionUsageDeclaration
    : ( ownedReferenceSubsetting
        featureSpecializationPart?
      | ACTION usageDeclaration
      )
      valuePart?
    ;

// ActionNode : ActionUsage =
//     ControlNode
//     | SendNode | AcceptNode
//     | AssignmentNode
//     | TerminateNode
//     | IfNode | WhileLoopNode | ForLoopNode
actionNode
    : controlNode
    | sendNode
    | acceptNode
    | assignmentNode
    | terminateNode
    | ifNode
    | whileLoopNode
    | forLoopNode
    ;

// ActionNodeUsageDeclaration : ActionUsage =
//     'action' UsageDeclaration?
actionNodeUsageDeclaration
    : ACTION usageDeclaration?
    ;

// ActionNodePrefix : ActionUsage =
//     OccurrenceUsagePrefix ActionNodeUsageDeclaration?
actionNodePrefix
    : occurrenceUsagePrefix actionNodeUsageDeclaration?
    ;

// 8.2.2.17.3 Control Nodes

// ControlNode =
//     MergeNode | DecisionNode | JoinNode | ForkNode
controlNode
    : mergeNode
    | decisionNode
    | joinNode
    | forkNode
    ;

// ControlNodePrefix : OccurrenceUsage =
//     RefPrefix
//     ( isIndividual ?= 'individual' )?
//     ( portionKind = PortionKind { isPortion = true } )?
//     UsageExtensionKeyword*
controlNodePrefix
    : refPrefix
      ( isIndividual=INDIVIDUAL )?
      ( portionKind=portionKindToken )?
      usageExtensionKeyword*
    ;

// MergeNode =
//     ControlNodePrefix
//     isComposite ?= 'merge' UsageDeclaration
//     ActionBody
mergeNode
    : controlNodePrefix
      isComposite=MERGE usageDeclaration
      actionBody
    ;

// DecisionNode =
//     ControlNodePrefix
//     isComposite ?= 'decide' UsageDeclaration
//     ActionBody
decisionNode
    : controlNodePrefix
      isComposite=DECIDE usageDeclaration
      actionBody
    ;

// JoinNode =
//     ControlNodePrefix
//     isComposite ?= 'join' UsageDeclaration
//     ActionBody
joinNode
    : controlNodePrefix
      isComposite=JOIN usageDeclaration
      actionBody
    ;

// ForkNode =
//     ControlNodePrefix
//     isComposite ?= 'fork' UsageDeclaration
//     ActionBody
forkNode
    : controlNodePrefix
      isComposite=FORK usageDeclaration
      actionBody
    ;

// 8.2.2.17.4 Send and Accept Action Usages

// AcceptNode : AcceptActionUsage =
//     OccurrenceUsagePrefix
//     AcceptNodeDeclaration ActionBody
acceptNode
    : occurrenceUsagePrefix
      acceptNodeDeclaration actionBody
    ;

// AcceptNodeDeclaration : AcceptActionUsage =
//     ActionNodeUsageDeclaration?
//     'accept' AcceptParameterPart
acceptNodeDeclaration
    : actionNodeUsageDeclaration?
      ACCEPT acceptParameterPart
    ;

// AcceptParameterPart : AcceptActionUsage =
//     ownedRelationship += PayloadParameterMember
//     ( 'via' ownedRelationship += NodeParameterMember )?
acceptParameterPart
    : payloadParameterMember
      ( VIA nodeParameterMember )?
    ;

// PayloadParameterMember : ParameterMembership =
//     ownedRelatedElement += PayloadParameter
payloadParameterMember
    : payloadParameter
    ;

// PayloadParameter : ReferenceUsage =
//     PayloadFeature
//     | Identification PayloadFeatureSpecializationPart?
//       TriggerValuePart
payloadParameter
    : payloadFeature
    | identification payloadFeatureSpecializationPart?
      triggerValuePart
    ;

// TriggerValuePart : Feature =
//     ownedRelationship += TriggerFeatureValue
triggerValuePart
    : triggerFeatureValue
    ;

// TriggerFeatureValue : FeatureValue =
//     ownedRelatedElement += TriggerExpression
triggerFeatureValue
    : triggerExpression
    ;

// TriggerExpression : TriggerInvocationExpression =
//     kind = ( 'at' | 'after' )
//     ownedRelationship += ArgumentMember
//     | kind = 'when'
//     ownedRelationship += ArgumentExpressionMember
triggerExpression
    : kind=( AT | AFTER )
      argumentMember
    | kind=WHEN
      argumentExpressionMember
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
    : value=ownedExpression
    ;

// ArgumentExpressionMember : ParameterMembership =
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
//     ownedRelatedElement += OwnedExpressionReference
argumentExpressionValue
    : ownedExpressionReference
    ;

// SendNode : SendActionUsage =
//     OccurrenceUsagePrefix ActionUsageDeclaration? 'send'
//     ( ownedRelationship += NodeParameterMember SenderReceiverPart?
//     | ownedRelationship += EmptyParameterMember SendReceiverPart )?
//     ActionBody
sendNode
    : occurrenceUsagePrefix actionUsageDeclaration? SEND
      ( nodeParameterMember senderReceiverPart?
      | emptyParameterMember senderReceiverPart
      )?
      actionBody
    ;

// SendNodeDeclaration : SendActionUsage =
//     ActionNodeUsageDeclaration? 'send'
//     ownedRelationship += NodeParameterMember SenderReceiverPart?
sendNodeDeclaration
    : actionNodeUsageDeclaration? SEND
      nodeParameterMember senderReceiverPart?
    ;

// SenderReceiverPart : SendActionUsage =
//     'via' ownedRelationship += NodeParameterMember
//     ( 'to' ownedRelationship += NodeParameterMember )?
//     | ownedRelationship += EmptyParameterMember
//       'to' ownedRelationship += NodeParameterMember
senderReceiverPart
    : VIA nodeParameterMember
      ( TO nodeParameterMember )?
    | emptyParameterMember
      TO nodeParameterMember
    ;

// NodeParameterMember : ParameterMembership =
//     ownedRelatedElement += NodeParameter
nodeParameterMember
    : nodeParameter
    ;

// NodeParameter : ReferenceUsage =
//     ownedRelationship += FeatureBinding
nodeParameter
    : featureBinding
    ;

// FeatureBinding : FeatureValue =
//     ownedRelatedElement += OwnedExpression
featureBinding
    : ownedExpression
    ;

// EmptyParameterMember : ParameterMembership =
//     ownedRelatedElement += EmptyUsage
emptyParameterMember
    : emptyUsage
    ;

// EmptyUsage : ReferenceUsage =
//     {}
emptyUsage
    : // empty
    ;

// 8.2.2.17.5 Assignment Action Usages

// AssignmentNode : AssignmentActionUsage =
//     OccurrenceUsagePrefix
//     AssignmentNodeDeclaration ActionBody
assignmentNode
    : occurrenceUsagePrefix
      assignmentNodeDeclaration actionBody
    ;

// AssignmentNodeDeclaration : ActionUsage =
//     ( ActionNodeUsageDeclaration )? 'assign'
//     ownedRelationship += AssignmentTargetMember
//     ownedRelationship += FeatureChainMember ':='
//     ownedRelationship += NodeParameterMember
assignmentNodeDeclaration
    : actionNodeUsageDeclaration? ASSIGN
      assignmentTargetMember
      featureChainMember COLON_EQUALS
      nodeParameterMember
    ;

// AssignmentTargetMember : ParameterMembership =
//     ownedRelatedElement += AssignmentTargetParameter
assignmentTargetMember
    : assignmentTargetParameter
    ;

// AssignmentTargetParameter : ReferenceUsage =
//     ( ownedRelationship += AssignmentTargetBinding '.' )?
assignmentTargetParameter
    : ( assignmentTargetBinding DOT )?
    ;

// AssignmentTargetBinding : FeatureValue =
//     ownedRelatedElement += NonFeatureChainPrimaryExpression
assignmentTargetBinding
    : nonFeatureChainPrimaryExpression
    ;

// FeatureChainMember : Membership =
//     memberElement = [QualifiedName]
//     | OwnedFeatureChainMember
featureChainMember
    : qualifiedName
    | ownedFeatureChainMember
    ;

// OwnedFeatureChainMember : OwningMembership =
//     ownedRelatedElement += OwnedFeatureChain
ownedFeatureChainMember
    : ownedFeatureChain
    ;

// 8.2.2.17.6 Terminate Action Usages

// TerminateNode : TerminateActionUsage =
//     OccurrenceUsagePrefix ActionNodeUsageDeclaration?
//     'terminate' ( ownedRelationship += NodeParameterMember )?
//     ActionBody
terminateNode
    : occurrenceUsagePrefix actionNodeUsageDeclaration?
      TERMINATE nodeParameterMember?
      actionBody
    ;

// 8.2.2.17.7 Structured Control Action Usages

// IfNode : IfActionUsage =
//     ActionNodePrefix
//     'if' ownedRelationship += ExpressionParameterMember
//     ownedRelationship += ActionBodyParameterMember
//     ( 'else' ownedRelationship +=
//       ( ActionBodyParameterMember | IfNodeParameterMember ) )?
ifNode
    : actionNodePrefix
      IF expressionParameterMember
      actionBodyParameterMember
      ( ELSE ( actionBodyParameterMember | ifNodeParameterMember ) )?
    ;

// ExpressionParameterMember : ParameterMembership =
//     ownedRelatedElement += OwnedExpression
expressionParameterMember
    : ownedExpression
    ;

// ActionBodyParameterMember : ParameterMembership =
//     ownedRelatedElement += ActionBodyParameter
actionBodyParameterMember
    : actionBodyParameter
    ;

// ActionBodyParameter : ActionUsage =
//     ( 'action' UsageDeclaration? )?
//     '{' ActionBodyItem* '}'
actionBodyParameter
    : ( ACTION usageDeclaration? )?
      LBRACE actionBodyItem* RBRACE
    ;

// IfNodeParameterMember : ParameterMembership =
//     ownedRelatedElement += IfNode
ifNodeParameterMember
    : ifNode
    ;

// WhileLoopNode : WhileLoopActionUsage =
//     ActionNodePrefix
//     ( 'while' ownedRelationship += ExpressionParameterMember
//       | 'loop' ownedRelationship += EmptyParameterMember
//     )
//     ownedRelationship += ActionBodyParameterMember
//     ( 'until' ownedRelationship += ExpressionParameterMember ';' )?
whileLoopNode
    : actionNodePrefix
      ( WHILE expressionParameterMember
      | LOOP emptyParameterMember
      )
      actionBodyParameterMember
      ( UNTIL expressionParameterMember SEMICOLON )?
    ;

// ForLoopNode : ForLoopActionUsage =
//     ActionNodePrefix
//     'for' ownedRelationship += ForVariableDeclarationMember
//     'in' ownedRelationship += NodeParameterMember
//     ownedRelationship += ActionBodyParameterMember
forLoopNode
    : actionNodePrefix
      FOR forVariableDeclarationMember
      IN nodeParameterMember
      actionBodyParameterMember
    ;

// ForVariableDeclarationMember : FeatureMembership =
//     ownedRelatedElement += ForVariableDeclaration
forVariableDeclarationMember
    : forVariableDeclaration
    ;

// ForVariableDeclaration : ReferenceUsage =
//     UsageDeclaration
forVariableDeclaration
    : usageDeclaration
    ;

// 8.2.2.17.8 Action Successions

// ActionTargetSuccession : Usage =
//     ( TargetSuccession | GuardedTargetSuccession | DefaultTargetSuccession )
//     UsageBody
actionTargetSuccession
    : ( targetSuccession | guardedTargetSuccession | defaultTargetSuccession )
      usageBody
    ;

// TargetSuccession : SuccessionAsUsage =
//     ownedRelationship += SourceEndMember
//     'then' ownedRelationship += ConnectorEndMember
targetSuccession
    : sourceEndMember
      THEN connectorEndMember
    ;

// GuardedTargetSuccession : TransitionUsage =
//     ownedRelationship += GuardExpressionMember
//     'then' ownedRelationship += TransitionSuccessionMember
guardedTargetSuccession
    : guardExpressionMember
      THEN transitionSuccessionMember
    ;

// DefaultTargetSuccession : TransitionUsage =
//     'else' ownedRelationship += TransitionSuccessionMember
defaultTargetSuccession
    : ELSE transitionSuccessionMember
    ;

// GuardedSuccession : TransitionUsage =
//     ( 'succession' UsageDeclaration )?
//     'first' ownedRelationship += FeatureChainMember
//     ownedRelationship += GuardExpressionMember
//     'then' ownedRelationship += TransitionSuccessionMember
//     UsageBody
guardedSuccession
    : ( SUCCESSION usageDeclaration )?
      FIRST featureChainMember
      guardExpressionMember
      THEN transitionSuccessionMember
      usageBody
    ;

// 8.2.2.18 States Textual Notation
// 8.2.2.18.1 State Definitions

// StateDefinition : StateDefinition =
//     OccurrenceDefinitionPrefix 'state' 'def'
//     DefinitionDeclaration StateDefBody
stateDefinition
    : occurrenceDefinitionPrefix STATE DEF
      definitionDeclaration stateDefBody
    ;

// StateDefBody : StateDefinition =
//     ';'
//     | ( isParallel ?= 'parallel' )?
//       '{' StateBodyItem* '}'
stateDefBody
    : SEMICOLON
    | PARALLEL? LBRACE stateBodyItem* RBRACE
    ;

// StateBodyItem : Type =
//     NonBehaviorBodyItem
//     | ( ownedRelationship += SourceSuccessionMember )?
//       ownedRelationship += BehaviorUsageMember
//       ( ownedRelationship += TargetTransitionUsageMember )*
//     | ownedRelationship += TransitionUsageMember
//     | ownedRelationship += EntryActionMember
//       ( ownedRelationship += EntryTransitionMember )*
//     | ownedRelationship += DoActionMember
//     | ownedRelationship += ExitActionMember
stateBodyItem
    : nonBehaviorBodyItem
    | sourceSuccessionMember? behaviorUsageMember targetTransitionUsageMember*
    | transitionUsageMember
    | entryActionMember entryTransitionMember*
    | doActionMember
    | exitActionMember
    ;

// EntryActionMember : StateSubactionMembership =
//     MemberPrefix kind = 'entry'
//     ownedRelatedElement += StateActionUsage
entryActionMember
    : memberPrefix ENTRY stateActionUsage
    ;

// DoActionMember : StateSubactionMembership =
//     MemberPrefix kind = 'do'
//     ownedRelatedElement += StateActionUsage
doActionMember
    : memberPrefix DO stateActionUsage
    ;

// ExitActionMember : StateSubactionMembership =
//     MemberPrefix kind = 'exit'
//     ownedRelatedElement += StateActionUsage
exitActionMember
    : memberPrefix EXIT stateActionUsage
    ;

// EntryTransitionMember : FeatureMembership =
//     MemberPrefix
//     ( ownedRelatedElement += GuardedTargetSuccession
//     | 'then' ownedRelatedElement += TargetSuccession
//     ) ';'
// LOCAL PATCH (sysml2-experiments): upstream had `THEN targetSuccession`, but
// targetSuccession already contains 'then' (sourceEndMember THEN connectorEnd),
// so the spec form `entry; then S1;` failed and only `then then S1;` parsed.
entryTransitionMember
    : memberPrefix
      ( guardedTargetSuccession
      | targetSuccession
      ) SEMICOLON
    ;

// StateActionUsage : ActionUsage =
//     EmptyActionUsage ';'
//     | StatePerformActionUsage
//     | StateAcceptActionUsage
//     | StateSendActionUsage
//     | StateAssignmentActionUsage
stateActionUsage
    : emptyActionUsage SEMICOLON
    | statePerformActionUsage
    | stateAcceptActionUsage
    | stateSendActionUsage
    | stateAssignmentActionUsage
    ;

// EmptyActionUsage : ActionUsage =
//     {}
emptyActionUsage
    : // empty
    ;

// StatePerformActionUsage : PerformActionUsage =
//     PerformActionUsageDeclaration ActionBody
statePerformActionUsage
    : performActionUsageDeclaration actionBody
    ;

// StateAcceptActionUsage : AcceptActionUsage =
//     AcceptNodeDeclaration ActionBody
stateAcceptActionUsage
    : acceptNodeDeclaration actionBody
    ;

// StateSendActionUsage : SendActionUsage =
//     SendNodeDeclaration ActionBody
stateSendActionUsage
    : sendNodeDeclaration actionBody
    ;

// StateAssignmentActionUsage : AssignmentActionUsage =
//     AssignmentNodeDeclaration ActionBody
stateAssignmentActionUsage
    : assignmentNodeDeclaration actionBody
    ;

// TransitionUsageMember : FeatureMembership =
//     MemberPrefix ownedRelatedElement += TransitionUsage
transitionUsageMember
    : memberPrefix transitionUsage
    ;

// TargetTransitionUsageMember : FeatureMembership =
//     MemberPrefix ownedRelatedElement += TargetTransitionUsage
targetTransitionUsageMember
    : memberPrefix targetTransitionUsage
    ;

// 8.2.2.18.2 State Usages

// StateUsage : StateUsage =
//     OccurrenceUsagePrefix 'state'
//     ActionUsageDeclaration StateUsageBody
stateUsage
    : occurrenceUsagePrefix STATE
      actionUsageDeclaration stateUsageBody
    ;

// StateUsageBody : StateUsage =
//     ';'
//     | ( isParallel ?= 'parallel' )?
//       '{' StateBodyItem* '}'
stateUsageBody
    : SEMICOLON
    | PARALLEL? LBRACE stateBodyItem* RBRACE
    ;

// ExhibitStateUsage : ExhibitStateUsage =
//     OccurrenceUsagePrefix 'exhibit'
//     ( ownedRelationship += OwnedReferenceSubsetting
//       FeatureSpecializationPart?
//     | 'state' UsageDeclaration )
//     ValuePart? StateUsageBody
exhibitStateUsage
    : occurrenceUsagePrefix EXHIBIT
      ( ownedReferenceSubsetting featureSpecializationPart?
      | STATE usageDeclaration
      )
      valuePart? stateUsageBody
    ;

// 8.2.2.18.3 Transition Usages

// TransitionUsage : TransitionUsage =
//     'transition' ( UsageDeclaration 'first' )?
//     ownedRelationship += FeatureChainMember
//     ownedRelationship += EmptyParameterMember
//     ( ownedRelationship += EmptyParameterMember
//       ownedRelationship += TriggerActionMember )?
//     ( ownedRelationship += GuardExpressionMember )?
//     ( ownedRelationship += EffectBehaviorMember )?
//     'then' ownedRelationship += TransitionSuccessionMember
//     ActionBody
transitionUsage
    : TRANSITION ( usageDeclaration FIRST )?
      featureChainMember
      emptyParameterMember
      ( emptyParameterMember triggerActionMember )?
      guardExpressionMember?
      effectBehaviorMember?
      THEN transitionSuccessionMember
      actionBody
    ;

// TargetTransitionUsage : TransitionUsage =
//     ownedRelationship += EmptyParameterMember
//     ( 'transition'
//       ( ownedRelationship += EmptyParameterMember
//         ownedRelationship += TriggerActionMember )?
//       ( ownedRelationship += GuardExpressionMember )?
//       ( ownedRelationship += EffectBehaviorMember )?
//     | ownedRelationship += EmptyParameterMember
//       ownedRelationship += TriggerActionMember
//       ( ownedRelationship += GuardExpressionMember )?
//       ( ownedRelationship += EffectBehaviorMember )?
//     | ownedRelationship += GuardExpressionMember
//       ( ownedRelationship += EffectBehaviorMember )?
//     )?
//     ActionBody
//     'then' ownedRelationship += TransitionSuccessionMember
targetTransitionUsage
    : emptyParameterMember
      ( TRANSITION
        ( emptyParameterMember triggerActionMember )?
        guardExpressionMember?
        effectBehaviorMember?
      | emptyParameterMember triggerActionMember
        guardExpressionMember?
        effectBehaviorMember?
      | guardExpressionMember effectBehaviorMember?
      )?
      actionBody
      THEN transitionSuccessionMember
    ;

// TriggerActionMember : TransitionFeatureMembership =
//     'accept' { kind = 'trigger' } ownedRelatedElement += TriggerAction
triggerActionMember
    : ACCEPT triggerAction
    ;

// TriggerAction : AcceptActionUsage =
//     AcceptParameterPart
triggerAction
    : acceptParameterPart
    ;

// GuardExpressionMember : TransitionFeatureMembership =
//     'if' { kind = 'guard' } ownedRelatedElement += OwnedExpression
guardExpressionMember
    : IF ownedExpression
    ;

// EffectBehaviorMember : TransitionFeatureMembership =
//     'do' { kind = 'effect' } ownedRelatedElement += EffectBehaviorUsage
effectBehaviorMember
    : DO effectBehaviorUsage
    ;

// EffectBehaviorUsage : ActionUsage =
//     EmptyActionUsage
//     | TransitionPerformActionUsage
//     | TransitionAcceptActionUsage
//     | TransitionSendActionUsage
//     | TransitionAssignmentActionUsage
effectBehaviorUsage
    : emptyActionUsage
    | transitionPerformActionUsage
    | transitionAcceptActionUsage
    | transitionSendActionUsage
    | transitionAssignmentActionUsage
    ;

// TransitionPerformActionUsage : PerformActionUsage =
//     PerformActionUsageDeclaration ( '{' ActionBodyItem* '}' )?
transitionPerformActionUsage
    : performActionUsageDeclaration ( LBRACE actionBodyItem* RBRACE )?
    ;

// TransitionAcceptActionUsage : AcceptActionUsage =
//     AcceptNodeDeclaration ( '{' ActionBodyItem* '}' )?
transitionAcceptActionUsage
    : acceptNodeDeclaration ( LBRACE actionBodyItem* RBRACE )?
    ;

// TransitionSendActionUsage : SendActionUsage =
//     SendNodeDeclaration ( '{' ActionBodyItem* '}' )?
transitionSendActionUsage
    : sendNodeDeclaration ( LBRACE actionBodyItem* RBRACE )?
    ;

// TransitionAssignmentActionUsage : AssignmentActionUsage =
//     AssignmentNodeDeclaration ( '{' ActionBodyItem* '}' )?
transitionAssignmentActionUsage
    : assignmentNodeDeclaration ( LBRACE actionBodyItem* RBRACE )?
    ;

// TransitionSuccessionMember : OwningMembership =
//     ownedRelatedElement += TransitionSuccession
transitionSuccessionMember
    : transitionSuccession
    ;

// TransitionSuccession : Succession =
//     ownedRelationship += EmptyEndMember
//     ownedRelationship += ConnectorEndMember
transitionSuccession
    : emptyEndMember connectorEndMember
    ;

// EmptyEndMember : EndFeatureMembership =
//     ownedRelatedElement += EmptyFeature
emptyEndMember
    : emptyFeature
    ;

// EmptyFeature : ReferenceUsage =
//     {}
emptyFeature
    : // empty
    ;

// 8.2.2.19 Calculations Textual Notation

// CalculationDefinition : CalculationDefinition =
//     OccurrenceDefinitionPrefix 'calc' 'def'
//     DefinitionDeclaration CalculationBody
calculationDefinition
    : occurrenceDefinitionPrefix CALC DEF
      definitionDeclaration calculationBody
    ;

// CalculationUsage : CalculationUsage =
//     OccurrenceUsagePrefix 'calc'
//     ActionUsageDeclaration CalculationBody
calculationUsage
    : occurrenceUsagePrefix CALC
      calculationUsageDeclaration calculationBody
    ;

calculationUsageDeclaration
    : actionUsageDeclaration
    ;

// CalculationBody : Type =
//     ';' | '{' CalculationBodyPart '}'
calculationBody
    : SEMICOLON
    | LBRACE calculationBodyPart RBRACE
    ;

// CalculationBodyPart : Type =
//     CalculationBodyItem*
//     ( ownedRelationship += ResultExpressionMember )?
calculationBodyPart
    : calculationBodyItem*
      resultExpressionMember?
    ;

// CalculationBodyItem : Type =
//     ActionBodyItem
//     | ownedRelationship += ReturnParameterMember
calculationBodyItem
    : actionBodyItem
    | returnParameterMember
    ;

// ReturnParameterMember : ReturnParameterMembership =
//     MemberPrefix? 'return' ownedRelatedElement += UsageElement
returnParameterMember
    : memberPrefix? RETURN usageElement
    ;

// ResultExpressionMember : ResultExpressionMembership =
//     MemberPrefix? ownedRelatedElement += OwnedExpression
resultExpressionMember
    : memberPrefix? ownedExpression
    ;

// 8.2.2.20 Constraints Textual Notation

// ConstraintDefinition : ConstraintDefinition =
//     OccurrenceDefinitionPrefix 'constraint' 'def'
//     DefinitionDeclaration CalculationBody
constraintDefinition
    : occurrenceDefinitionPrefix CONSTRAINT DEF
      definitionDeclaration calculationBody
    ;

// ConstraintUsage : ConstraintUsage =
//     OccurrenceUsagePrefix 'constraint'
//     ConstraintUsageDeclaration CalculationBody
constraintUsage
    : occurrenceUsagePrefix CONSTRAINT
      constraintUsageDeclaration calculationBody
    ;

// AssertConstraintUsage : AssertConstraintUsage =
//     OccurrenceUsagePrefix 'assert' ( isNegated ?= 'not' )?
//     ( ownedRelationship += OwnedReferenceSubsetting
//       FeatureSpecializationPart?
//     | 'constraint' ConstraintUsageDeclaration )
//     CalculationBody
assertConstraintUsage
    : occurrenceUsagePrefix ASSERT NOT?
      ( ownedReferenceSubsetting featureSpecializationPart?
      | CONSTRAINT constraintUsageDeclaration
      )
      calculationBody
    ;

// ConstraintUsageDeclaration : ConstraintUsage =
//     UsageDeclaration ValuePart?
constraintUsageDeclaration
    : usageDeclaration valuePart?
    ;

// 8.2.2.21 Requirements Textual Notation
// 8.2.2.21.1 Requirement Definitions

// RequirementDefinition : RequirementDefinition =
//     OccurrenceDefinitionPrefix 'requirement' 'def'
//     DefinitionDeclaration RequirementBody
requirementDefinition
    : occurrenceDefinitionPrefix REQUIREMENT DEF
      definitionDeclaration requirementBody
    ;

// RequirementBody : Type =
//     ';' | '{' RequirementBodyItem* '}'
requirementBody
    : SEMICOLON
    | LBRACE requirementBodyItem* RBRACE
    ;

// RequirementBodyItem : Type =
//     DefinitionBodyItem
//     | ownedRelationship += SubjectMember
//     | ownedRelationship += RequirementConstraintMember
//     | ownedRelationship += FramedConcernMember
//     | ownedRelationship += RequirementVerificationMember
//     | ownedRelationship += ActorMember
//     | ownedRelationship += StakeholderMember
requirementBodyItem
    : definitionBodyItem
    | subjectMember
    | requirementConstraintMember
    | framedConcernMember
    | requirementVerificationMember
    | actorMember
    | stakeholderMember
    ;

// SubjectMember : SubjectMembership =
//     MemberPrefix ownedRelatedElement += SubjectUsage
subjectMember
    : memberPrefix subjectUsage
    ;

// SubjectUsage : ReferenceUsage =
//     'subject' UsageExtensionKeyword* Usage
subjectUsage
    : SUBJECT usageExtensionKeyword* usage
    ;

// RequirementConstraintMember : RequirementConstraintMembership =
//     MemberPrefix? RequirementKind
//     ownedRelatedElement += RequirementConstraintUsage
requirementConstraintMember
    : memberPrefix? requirementKind requirementConstraintUsage
    ;

// RequirementKind : RequirementConstraintMembership =
//     'assume' { kind = 'assumption' }
//     | 'require' { kind = 'requirement' }
requirementKind
    : ASSUME
    | REQUIRE
    ;

// RequirementConstraintUsage : ConstraintUsage =
//     ownedRelationship += OwnedReferenceSubsetting
//     FeatureSpecializationPart? RequirementBody
//     | ( UsageExtensionKeyword* 'constraint'
//       | UsageExtensionKeyword+ )
//       ConstraintUsageDeclaration CalculationBody
requirementConstraintUsage
    : ownedReferenceSubsetting featureSpecializationPart? requirementBody
    | ( usageExtensionKeyword* CONSTRAINT
      | usageExtensionKeyword+
      )
      constraintUsageDeclaration calculationBody
    ;

// FramedConcernMember : FramedConcernMembership =
//     MemberPrefix? 'frame'
//     ownedRelatedElement += FramedConcernUsage
framedConcernMember
    : memberPrefix? FRAME framedConcernUsage
    ;

// FramedConcernUsage : ConcernUsage =
//     ownedRelationship += OwnedReferenceSubsetting
//     FeatureSpecializationPart? CalculationBody
//     | ( UsageExtensionKeyword* 'concern'
//       | UsageExtensionKeyword+ )
//       CalculationUsageDeclaration CalculationBody
framedConcernUsage
    : ownedReferenceSubsetting featureSpecializationPart? calculationBody
    | ( usageExtensionKeyword* CONCERN
      | usageExtensionKeyword+
      )
      calculationUsageDeclaration calculationBody
    ;

// ActorMember : ActorMembership =
//     MemberPrefix ownedRelatedElement += ActorUsage
actorMember
    : memberPrefix actorUsage
    ;

// ActorUsage : PartUsage =
//     'actor' UsageExtensionKeyword* Usage
actorUsage
    : ACTOR usageExtensionKeyword* usage
    ;

// StakeholderMember : StakeholderMembership =
//     MemberPrefix ownedRelatedElement += StakeholderUsage
stakeholderMember
    : memberPrefix stakeholderUsage
    ;

// StakeholderUsage : PartUsage =
//     'stakeholder' UsageExtensionKeyword* Usage
stakeholderUsage
    : STAKEHOLDER usageExtensionKeyword* usage
    ;

// 8.2.2.21.2 Requirement Usages

// RequirementUsage : RequirementUsage =
//     OccurrenceUsagePrefix 'requirement'
//     ConstraintUsageDeclaration RequirementBody
requirementUsage
    : occurrenceUsagePrefix REQUIREMENT
      constraintUsageDeclaration requirementBody
    ;

// SatisfyRequirementUsage : SatisfyRequirementUsage =
//     OccurrenceUsagePrefix 'assert' ( isNegated ?= 'not' )? 'satisfy'
//     ( ownedRelationship += OwnedReferenceSubsetting
//       FeatureSpecializationPart?
//     | 'requirement' UsageDeclaration )
//     ValuePart?
//     ( 'by' ownedRelationship += SatisfactionSubjectMember )?
//     RequirementBody
// NOTE: Made ASSERT optional to support 'satisfy requirement' in views without 'assert'
satisfyRequirementUsage
    : occurrenceUsagePrefix ASSERT? NOT? SATISFY
      ( ownedReferenceSubsetting featureSpecializationPart?
      | REQUIREMENT usageDeclaration
      )
      valuePart?
      ( BY satisfactionSubjectMember )?
      requirementBody
    ;

// SatisfactionSubjectMember : SubjectMembership =
//     ownedRelatedElement += SatisfactionParameter
satisfactionSubjectMember
    : satisfactionParameter
    ;

// SatisfactionParameter : ReferenceUsage =
//     ownedRelationship += SatisfactionFeatureValue
satisfactionParameter
    : satisfactionFeatureValue
    ;

// SatisfactionFeatureValue : FeatureValue =
//     ownedRelatedElement += SatisfactionReferenceExpression
satisfactionFeatureValue
    : satisfactionReferenceExpression
    ;

// SatisfactionReferenceExpression : FeatureReferenceExpression =
//     ownedRelationship += FeatureChainMember
satisfactionReferenceExpression
    : featureChainMember
    ;

// 8.2.2.21.3 Concerns

// ConcernDefinition : ConcernDefinition =
//     OccurrenceDefinitionPrefix 'concern' 'def'
//     DefinitionDeclaration RequirementBody
concernDefinition
    : occurrenceDefinitionPrefix CONCERN DEF
      definitionDeclaration requirementBody
    ;

// ConcernUsage : ConcernUsage =
//     OccurrenceUsagePrefix 'concern'
//     ConstraintUsageDeclaration RequirementBody
concernUsage
    : occurrenceUsagePrefix CONCERN
      constraintUsageDeclaration requirementBody
    ;

// 8.2.2.22 Cases Textual Notation

// CaseDefinition : CaseDefinition =
//     OccurrenceDefinitionPrefix 'case' 'def'
//     DefinitionDeclaration CaseBody
caseDefinition
    : occurrenceDefinitionPrefix CASE DEF
      definitionDeclaration caseBody
    ;

// CaseUsage : CaseUsage =
//     OccurrenceUsagePrefix 'case'
//     ConstraintUsageDeclaration CaseBody
caseUsage
    : occurrenceUsagePrefix CASE
      constraintUsageDeclaration caseBody
    ;

// CaseBody : Type =
//     ';'
//     | '{' CaseBodyItem*
//       ( ownedRelationship += ResultExpressionMember )?
//       '}'
caseBody
    : SEMICOLON
    | LBRACE caseBodyItem* resultExpressionMember? RBRACE
    ;

// CaseBodyItem : Type =
//     ActionBodyItem
//     | ownedRelationship += SubjectMember
//     | ownedRelationship += ActorMember
//     | ownedRelationship += ObjectiveMember
//     | ownedRelationship += ReturnParameterMember  // Added for 'return' statements
caseBodyItem
    : actionBodyItem
    | subjectMember
    | actorMember
    | objectiveMember
    | returnParameterMember
    ;

// ObjectiveMember : ObjectiveMembership =
//     MemberPrefix 'objective'
//     ownedRelatedElement += ObjectiveRequirementUsage
objectiveMember
    : memberPrefix OBJECTIVE objectiveRequirementUsage
    ;

// ObjectiveRequirementUsage : RequirementUsage =
//     UsageExtensionKeyword* ConstraintUsageDeclaration
//     RequirementBody
objectiveRequirementUsage
    : usageExtensionKeyword* constraintUsageDeclaration
      requirementBody
    ;

// 8.2.2.23 Analysis Cases Textual Notation

// AnalysisCaseDefinition : AnalysisCaseDefinition =
//     OccurrenceDefinitionPrefix 'analysis' 'def'
//     DefinitionDeclaration CaseBody
analysisCaseDefinition
    : occurrenceDefinitionPrefix ANALYSIS DEF
      definitionDeclaration caseBody
    ;

// AnalysisCaseUsage : AnalysisCaseUsage =
//     OccurrenceUsagePrefix 'analysis'
//     ConstraintUsageDeclaration CaseBody
analysisCaseUsage
    : occurrenceUsagePrefix ANALYSIS
      constraintUsageDeclaration caseBody
    ;

// 8.2.2.24 Verification Cases Textual Notation

// VerificationCaseDefinition : VerificationCaseDefinition =
//     OccurrenceDefinitionPrefix 'verification' 'def'
//     DefinitionDeclaration CaseBody
verificationCaseDefinition
    : occurrenceDefinitionPrefix VERIFICATION DEF
      definitionDeclaration caseBody
    ;

// VerificationCaseUsage : VerificationCaseUsage =
//     OccurrenceUsagePrefix 'verification'
//     ConstraintUsageDeclaration CaseBody
verificationCaseUsage
    : occurrenceUsagePrefix VERIFICATION
      constraintUsageDeclaration caseBody
    ;

// RequirementVerificationMember : RequirementVerificationMembership =
//     MemberPrefix 'verify' { kind = 'requirement' }
//     ownedRelatedElement += RequirementVerificationUsage
requirementVerificationMember
    : memberPrefix VERIFY requirementVerificationUsage
    ;

// RequirementVerificationUsage : RequirementUsage =
//     ownedRelationship += OwnedReferenceSubsetting
//     FeatureSpecialization* RequirementBody
//     | ( UsageExtensionKeyword* 'requirement'
//       | UsageExtensionKeyword+ )
//       ConstraintUsageDeclaration RequirementBody
requirementVerificationUsage
    : ownedReferenceSubsetting featureSpecialization* requirementBody
    | ( usageExtensionKeyword* REQUIREMENT
      | usageExtensionKeyword+
      )
      constraintUsageDeclaration requirementBody
    ;

// 8.2.2.25 Use Cases Textual Notation

// UseCaseDefinition : UseCaseDefinition =
//     OccurrenceDefinitionPrefix 'use' 'case' 'def'
//     DefinitionDeclaration CaseBody
useCaseDefinition
    : occurrenceDefinitionPrefix USE CASE DEF
      definitionDeclaration caseBody
    ;

// UseCaseUsage : UseCaseUsage =
//     OccurrenceUsagePrefix 'use' 'case'
//     ConstraintUsageDeclaration CaseBody
useCaseUsage
    : occurrenceUsagePrefix USE CASE
      constraintUsageDeclaration caseBody
    ;

// IncludeUseCaseUsage : IncludeUseCaseUsage =
//     OccurrenceUsagePrefix 'include'
//     ( ownedRelationship += OwnedReferenceSubsetting
//       FeatureSpecializationPart?
//     | 'use' 'case' UsageDeclaration )
//     ValuePart?
//     CaseBody
includeUseCaseUsage
    : occurrenceUsagePrefix INCLUDE
      ( ownedReferenceSubsetting featureSpecializationPart?
      | USE CASE usageDeclaration
      )
      valuePart?
      caseBody
    ;

// 8.2.2.26 Views and Viewpoints Textual Notation
// 8.2.2.26.1 View Definitions

// ViewDefinition : ViewDefinition =
//     OccurrenceDefinitionPrefix 'view' 'def'
//     DefinitionDeclaration ViewDefinitionBody
viewDefinition
    : occurrenceDefinitionPrefix VIEW DEF
      definitionDeclaration viewDefinitionBody
    ;

// ViewDefinitionBody : ViewDefinition =
//     ';' | '{' ViewDefinitionBodyItem* '}'
viewDefinitionBody
    : SEMICOLON
    | LBRACE viewDefinitionBodyItem* RBRACE
    ;

// ViewDefinitionBodyItem : ViewDefinition =
//     DefinitionBodyItem
//     | ownedRelationship += ElementFilterMember
//     | ownedRelationship += ViewRenderingMember
viewDefinitionBodyItem
    : definitionBodyItem
    | elementFilterMember
    | viewRenderingMember
    ;

// ViewRenderingMember : ViewRenderingMembership =
//     MemberPrefix 'render'
//     ownedRelatedElement += ViewRenderingUsage
viewRenderingMember
    : memberPrefix RENDER viewRenderingUsage
    ;

// ViewRenderingUsage : RenderingUsage =
//     ownedRelationship += OwnedReferenceSubsetting
//     FeatureSpecializationPart?
//     UsageBody
//     | ( UsageExtensionKeyword* 'rendering'
//       | UsageExtensionKeyword+ )
//       Usage
viewRenderingUsage
    : ownedReferenceSubsetting featureSpecializationPart? usageBody
    | ( usageExtensionKeyword* RENDERING
      | usageExtensionKeyword+
      )
      usage
    ;

// 8.2.2.26.2 View Usages

// ViewUsage : ViewUsage =
//     OccurrenceUsagePrefix 'view'
//     UsageDeclaration? ValuePart?
//     ViewBody
viewUsage
    : occurrenceUsagePrefix VIEW
      usageDeclaration? valuePart?
      viewBody
    ;

// ViewBody : ViewUsage =
//     ';' | '{' ViewBodyItem* '}'
viewBody
    : SEMICOLON
    | LBRACE viewBodyItem* RBRACE
    ;

// ViewBodyItem : ViewUsage =
//     DefinitionBodyItem
//     | ownedRelationship += ElementFilterMember
//     | ownedRelationship += ViewRenderingMember
//     | ownedRelationship += Expose
//     | SatisfyRequirementUsage  // Added for 'satisfy requirement' in views
//     | RequirementConstraintMember  // Added for 'require' in views
viewBodyItem
    : definitionBodyItem
    | elementFilterMember
    | viewRenderingMember
    | expose
    | satisfyRequirementUsage
    | requirementConstraintMember
    ;

// Expose : Expose =
//     'expose' ( MembershipExpose | NamespaceExpose )
//     RelationshipBody
expose
    : EXPOSE ( membershipExpose | namespaceExpose )
      relationshipBody
    ;

// MembershipExpose : MembershipExpose =
//     MembershipImport
membershipExpose
    : membershipImport
    ;

// NamespaceExpose : NamespaceExpose =
//     NamespaceImport
namespaceExpose
    : namespaceImport
    ;

// 8.2.2.26.3 Viewpoints

// ViewpointDefinition : ViewpointDefinition =
//     OccurrenceDefinitionPrefix 'viewpoint' 'def'
//     DefinitionDeclaration RequirementBody
viewpointDefinition
    : occurrenceDefinitionPrefix VIEWPOINT DEF
      definitionDeclaration requirementBody
    ;

// ViewpointUsage : ViewpointUsage =
//     OccurrenceUsagePrefix 'viewpoint'
//     ConstraintUsageDeclaration RequirementBody
viewpointUsage
    : occurrenceUsagePrefix VIEWPOINT
      constraintUsageDeclaration requirementBody
    ;

// 8.2.2.26.4 Renderings

// RenderingDefinition : RenderingDefinition =
//     OccurrenceDefinitionPrefix 'rendering' 'def'
//     Definition
renderingDefinition
    : occurrenceDefinitionPrefix RENDERING DEF
      definition
    ;

// RenderingUsage : RenderingUsage =
//     OccurrenceUsagePrefix 'rendering'
//     Usage
renderingUsage
    : occurrenceUsagePrefix RENDERING
      usage
    ;

// 8.2.2.27 Metadata Textual Notation

// MetadataDefinition : MetadataDefinition =
//     ( isAbstract ?= 'abstract')? DefinitionExtensionKeyword*
//     'metadata' 'def' Definition
metadataDefinition
    : ABSTRACT? definitionExtensionKeyword*
      METADATA DEF definition
    ;

// PrefixMetadataAnnotation : Annotation =
//     '#' annotatingElement = PrefixMetadataUsage
//     { ownedRelatedElement += annotatingElement }
prefixMetadataAnnotation
    : HASH prefixMetadataUsage
    ;

// PrefixMetadataMember : OwningMembership =
//     '#' ownedRelatedElement = PrefixMetadataUsage
prefixMetadataMember
    : HASH prefixMetadataUsage
    ;

// PrefixMetadataUsage : MetadataUsage =
//     ownedRelationship += OwnedFeatureTyping
prefixMetadataUsage
    : ownedFeatureTyping
    ;

// MetadataUsage : MetadataUsage =
//     UsageExtensionKeyword* ( '@' | 'metadata' )
//     MetadataUsageDeclaration
//     ( 'about' ownedRelationship += Annotation
//       ( ',' ownedRelationship += Annotation )*
//     )?
//     MetadataBody
metadataUsage
    : usageExtensionKeyword* ( AT | METADATA )
      metadataUsageDeclaration
      ( ABOUT annotation ( COMMA annotation )* )?
      metadataBody
    ;

// MetadataUsageDeclaration : MetadataUsage =
//     ( Identification ( ':' | 'typed' 'by' ) )?
//     ownedRelationship += OwnedFeatureTyping
metadataUsageDeclaration
    : ( identification ( COLON | DEFINED BY ) )?
      ownedFeatureTyping
    ;

// MetadataBody : Type =
//     ';' |
//     '{' ( ownedRelationship += DefinitionMember
//         | ownedRelationship += MetadataBodyUsageMember
//         | ownedRelationship += AliasMember
//         | ownedRelationship += Import
//         )*
//     '}'
metadataBody
    : SEMICOLON
    | LBRACE ( definitionMember
             | metadataBodyUsageMember
             | aliasMember
             | import_
             )*
      RBRACE
    ;

// MetadataBodyUsageMember : FeatureMembership =
//     ownedMemberFeature = MetadataBodyUsage
metadataBodyUsageMember
    : metadataBodyUsage
    ;

// MetadataBodyUsage : ReferenceUsage =
//     'ref'? ( ':>>' | 'redefines' )? ownedRelationship += OwnedRedefinition
//     FeatureSpecializationPart? ValuePart?
//     MetadataBody
metadataBodyUsage
    : REF? ( redefinesToken)? ownedRedefinition
      featureSpecializationPart? valuePart?
      metadataBody
    ;

// ExtendedDefinition : Definition =
//     BasicDefinitionPrefix? DefinitionExtensionKeyword+
//     'def' Definition
extendedDefinition
    : basicDefinitionPrefix? definitionExtensionKeyword+
      DEF definition
    ;

// ExtendedUsage : Usage =
//     UnextendedUsagePrefix UsageExtensionKeyword+
//     Usage
extendedUsage
    : unextendedUsagePrefix usageExtensionKeyword+
      usage
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
    : ( identification ( COLON | DEFINED BY ) )?
      ownedFeatureTyping
    ;


// 8.2.5.8 Expressions Concrete Syntax (from KerML)
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

// The SysML spec does not redefine OwnedExpression — every reference in the
// SysML spec's EBNF productions (e.g. `guard-expression`, `result-compartment-
// contents`, `filters-compartment-element`) is a *use* of an undefined
// non-terminal. The spec defers expression semantics to KerML (see KerML 7.4.9).
// The rules below mirror KerML's `ownedExpression` and its precedence-grouped
// operator sub-rules so the SysML parser produces correctly-shaped expression
// trees (e.g. `a == b + c` → `a == (b + c)`). In ANTLR 4 left-recursive rules
// the FIRST listed alternative has the HIGHEST precedence.
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

// ConditionalBinaryOperator (mirrors KerML)
//     '??' | 'or' | 'and' | 'implies'
conditionalBinaryOperator
    : DOUBLE_QUESTION
    | OR
    | AND
    | IMPLIES
    ;

// BinaryOperator — composite rule mirroring KerML's `binaryOperator`. Not used
// directly by `ownedExpression` above (each precedence-grouped sub-rule is
// listed there explicitly), but kept as a parallel to KerML for any future
// caller that needs to reference the union by name.
binaryOperator
    : equalityOperator
    | relationalOperator
    | additiveOperator
    | multiplicativeOperator
    | exponentialOperator
    | bitwiseOperator
    | rangeOperator
    ;

// Precedence-grouped operator sub-rules (mirror KerML; used by `ownedExpression`
// alternatives above for correct precedence).

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

// UnaryOperator =
//     '+' | '-' | '~' | 'not'
unaryOperator
    : PLUS
    | MINUS
    | TILDE
    | NOT
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
//     '{' CalculationBodyPart '}'
expressionBody
    : LBRACE calculationBodyPart RBRACE
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

// ===== Lexer Rules =====

// SysML Reserved Keywords (in alphabetical order)
// These must be defined before BASIC_NAME to have higher priority in lexer matching

ABOUT : 'about' ;
ABSTRACT : 'abstract' ;
ACCEPT : 'accept' ;
ACTION : 'action' ;
ACTOR : 'actor' ;
AFTER : 'after' ;
ALIAS : 'alias' ;
ALL : 'all' ;
ALLOCATE : 'allocate' ;
ALLOCATION : 'allocation' ;
ANALYSIS : 'analysis' ;
AND : 'and' ;
AS : 'as' ;
ASSERT : 'assert' ;
ASSIGN : 'assign' ;
ASSUME : 'assume' ;
AT : 'at' ;
ATTRIBUTE : 'attribute' ;
BIND : 'bind' ;
BINDING : 'binding' ;
BY : 'by' ;
CALC : 'calc' ;
CASE : 'case' ;
COMMENT : 'comment' ;
CONCERN : 'concern' ;
CONNECT : 'connect' ;
CONNECTION : 'connection' ;
CONSTANT : 'constant' ;
CONSTRAINT : 'constraint' ;
CROSSES : 'crosses' ;
DECIDE : 'decide' ;
DEF : 'def' ;
DEFAULT : 'default' ;
DEFINED : 'defined' ;
DEPENDENCY : 'dependency' ;
DERIVED : 'derived' ;
DO : 'do' ;
DOC : 'doc' ;
ELSE : 'else' ;
END : 'end' ;
ENTRY : 'entry' ;
ENUM : 'enum' ;
EVENT : 'event' ;
EXHIBIT : 'exhibit' ;
EXIT : 'exit' ;
EXPOSE : 'expose' ;
FALSE : 'false' ;
FILTER : 'filter' ;
FIRST : 'first' ;
FLOW : 'flow' ;
FOR : 'for' ;
FORK : 'fork' ;
FRAME : 'frame' ;
FROM : 'from' ;
HASTYPE : 'hastype' ;
IF : 'if' ;
IMPLIES : 'implies' ;
IMPORT : 'import' ;
IN : 'in' ;
INCLUDE : 'include' ;
INDIVIDUAL : 'individual' ;
INOUT : 'inout' ;
INTERFACE : 'interface' ;
ISTYPE : 'istype' ;
ITEM : 'item' ;
JOIN : 'join' ;
LANGUAGE : 'language' ;
LIBRARY : 'library' ;
LOCALE : 'locale' ;
LOOP : 'loop' ;
MERGE : 'merge' ;
MESSAGE : 'message' ;
META : 'meta' ;
METADATA : 'metadata' ;
NEW : 'new' ;
NONUNIQUE : 'nonunique' ;
NOT : 'not' ;
NULL : 'null' ;
OBJECTIVE : 'objective' ;
OCCURRENCE : 'occurrence' ;
OF : 'of' ;
OR : 'or' ;
ORDERED : 'ordered' ;
OUT : 'out' ;
PACKAGE : 'package' ;
PARALLEL : 'parallel' ;
PART : 'part' ;
PERFORM : 'perform' ;
PORT : 'port' ;
PRIVATE : 'private' ;
PROTECTED : 'protected' ;
PUBLIC : 'public' ;
REDEFINES : 'redefines' ;
REF : 'ref' ;
REFERENCES : 'references' ;
RENDER : 'render' ;
RENDERING : 'rendering' ;
REP : 'rep' ;
REQUIRE : 'require' ;
REQUIREMENT : 'requirement' ;
RETURN : 'return' ;
SATISFY : 'satisfy' ;
SEND : 'send' ;
SNAPSHOT : 'snapshot' ;
SPECIALIZES : 'specializes' ;
STAKEHOLDER : 'stakeholder' ;
STANDARD : 'standard' ;
STATE : 'state' ;
SUBJECT : 'subject' ;
SUBSETS : 'subsets' ;
SUCCESSION : 'succession' ;
TERMINATE : 'terminate' ;
THEN : 'then' ;
TIMESLICE : 'timeslice' ;
TO : 'to' ;
TRANSITION : 'transition' ;
TRUE : 'true' ;
UNTIL : 'until' ;
USE : 'use' ;
VARIANT : 'variant' ;
VARIATION : 'variation' ;
VERIFICATION : 'verification' ;
VERIFY : 'verify' ;
VIA : 'via' ;
VIEW : 'view' ;
VIEWPOINT : 'viewpoint' ;
WHEN : 'when' ;
WHILE : 'while' ;
XOR : 'xor' ;

// Symbols
// Non-alphanumeric tokens, ordered by length (longest first) for proper matching

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
AT_SIGN : '@' ;
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
SINGLE_LINE_NOTE
    : '//' ~[\r\n]* -> channel(HIDDEN)
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

// 8.2.2.3 Names
// Notes:
// 1. The single_quote character is '. Characters within quotes form the name (quotes excluded).
// 2. ESCAPE_SEQUENCE: backslash sequences representing single characters (see Table 4)
//    Allowed escapes: \b \f \n \r \t \' \\ and newline continuation
// 3. BASIC_NAME must be defined AFTER reserved keywords to ensure proper lexer priority

// UNRESTRICTED_NAME: single_quote ( NAME_CHARACTER | ESCAPE_SEQUENCE )* single_quote
// NOTE: Must be a fragment so only NAME is emitted as a token
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
// 1. DECIMAL_VALUE may specify a natural literal or be part of a real literal
//    Sign is not included - negation is handled as an operator in Expression syntax
// 2. EXPONENTIAL_VALUE may be used in real literals
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
// 1. LINE_TERMINATOR defined at start of lexer rules
// 2. LINE_TEXT refers to characters in a text line that are not part of LINE_TERMINATOR
// 3. WHITE_SPACE separates tokens and is otherwise ignored, EXCEPT line terminators
//    are used to mark the end of single-line notes

// WHITE_SPACE: space | tab | form_feed
WS
    : [ \t\f]+ -> channel(HIDDEN)
    ;
